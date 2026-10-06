"""Chantier B — retrieval (docs/AI_CONTEXT_ENGINEERING.md §B), without any real network call.

Fake LLM through ``httpx.MockTransport``, hash embeddings (conftest), stub cross-encoder.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.context import rerank
from app.enums import CandidateType
from app.governance.policy import Candidate
from app.ingestion import contextual, pipeline
from app.llm import client as llm
from app.llm import guardrail
from app.models import Chunk
from app.search import opensearch, reranker_models
from tests.test_api_documents import _text, drain
from tests.test_feature_llm import FakeLLM, fake_llm  # noqa: F401

API = "/api/v1/projects"

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _chunk(cid: str, title: str, text: str, rrf: float) -> Candidate:
    c = Candidate(
        candidate_type=CandidateType.chunk,
        id=cid,
        title=title,
        text=text,
        classification=1,
        acl_principals=["project:x"],
        status="active",
        date=NOW,
        key=f"chunk:{cid}",
    )
    c.scores.rrf_norm = rrf
    return c


# --- B2: cross-encoder reranker ------------------------------------------------------------------------


def test_default_reranker_is_multilingual_and_permissive() -> None:
    model = settings.reranker_model
    assert model == reranker_models.DEFAULT_RERANKER_MODEL
    assert reranker_models.license_of(model) in reranker_models.PERMISSIVE_LICENSES
    reranker_models.ensure_registered(model)
    reranker_models.ensure_registered(model)  # idempotent
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    assert model in {m["model"] for m in TextCrossEncoder.list_supported_models()}
    assert reranker_models.license_of("jinaai/jina-reranker-v2-base-multilingual") == "cc-by-nc-4.0"


class _StubEncoder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, passages: list[str], batch_size: int = 16) -> list[float]:
        self.calls.append((query, passages))
        # Relevance = the passage mentions PostgreSQL.
        return [4.0 if "PostgreSQL" in p else -4.0 for p in passages]


async def test_cross_encoder_reorders_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubEncoder()
    monkeypatch.setattr(settings, "reranker", "fastembed")
    monkeypatch.setattr(rerank, "_encoder", stub)
    candidates = [
        _chunk("a", "Budget", "Le budget marketing est validé.", 0.9),
        _chunk("b", "Base", "Nous retenons PostgreSQL comme base principale.", 0.5),
    ]
    label = await rerank.rerank(
        candidates, query="Quelle base de données ?", query_terms=["base"], query_vector=None, now=NOW
    )
    assert label == f"fastembed:{settings.reranker_model}"
    assert stub.calls and stub.calls[0][0] == "Quelle base de données ?"
    best = max(candidates, key=lambda c: c.score)
    assert best.id == "b" and best.scores.cross_encoder is not None and best.scores.cross_encoder > 0.9

    class _Broken:
        def rerank(self, *_a: Any, **_k: Any) -> list[float]:
            raise RuntimeError("onnx failure")

    monkeypatch.setattr(rerank, "_encoder", _Broken())
    again = [_chunk("a", "Budget", "Budget marketing.", 0.9), _chunk("b", "Base", "PostgreSQL.", 0.5)]
    label = await rerank.rerank(again, query="base", query_terms=["base"], query_vector=None, now=NOW)
    assert label == "heuristic-v1 (repli)"
    assert max(again, key=lambda c: c.score).id == "a"


# --- B1: contextual retrieval -------------------------------------------------------------------------

LLM_PREAMBLE = "Extrait du dossier d'architecture Atlas consacré au choix de la base de données."
ARCHI = (
    "# Architecture Atlas\n\n## Persistance\n\nLe comité technique a retenu PostgreSQL 17 pour le service "
    "Atlas Facturation. Le module NOVA consomme les événements via Kafka. La migration est prévue au T2."
)


def _reply(prompt: str) -> str:
    return LLM_PREAMBLE if "<extrait>" in prompt else "{}"


def test_deterministic_preamble() -> None:
    doc = contextual.DocumentContext(
        title="Architecture Atlas",
        source_label="Wiki (Notes)",
        date=NOW,
        tags=["atlas"],
        classification=1,
    )
    item = contextual.PreambleInput(
        text=ARCHI, text_redacted=ARCHI, section="Architecture Atlas > Persistance"
    )
    preamble = contextual.deterministic_preamble(item, doc)
    assert preamble.startswith(
        "Document « Architecture Atlas » — section « Architecture Atlas > Persistance »"
    )
    assert "source : Wiki (Notes)" in preamble and "date : 2026-10-01" in preamble
    assert "NOVA" in preamble and "PostgreSQL" in preamble and "atlas" in preamble


async def _chunks(client: httpx.AsyncClient, slug: str, document_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"{API}/{slug}/documents/{document_id}")
    assert response.status_code == 200, response.text
    return response.json()["chunks"]


async def test_preamble_llm_guardrail_and_fallback(
    admin_client: httpx.AsyncClient,
    project: dict[str, Any],
    fake_llm: Callable[..., FakeLLM],  # noqa: F811
) -> None:
    slug = str(project["slug"])
    fake = fake_llm(_reply, provider="openai")
    c1 = await _text(admin_client, slug, title="Architecture Atlas", content=ARCHI, classification=1)
    c2 = await _text(admin_client, slug, title="Architecture Atlas (C2)", content=ARCHI, classification=2)
    skips = guardrail.skip_count()
    await drain()
    prompts = [b["messages"][-1]["content"] for b in fake.bodies()]
    preamble_prompts = [p for p in prompts if "<extrait>" in p]
    # C1 → LLM preamble; C2 is never sent to the (external) LLM.
    assert preamble_prompts and all("(C2)" not in p for p in preamble_prompts)
    assert guardrail.skip_count() > skips
    first = (await _chunks(admin_client, slug, c1["id"]))[0]
    assert first["context_source"] == "llm" and LLM_PREAMBLE in first["context_preamble"]
    second = (await _chunks(admin_client, slug, c2["id"]))[0]
    assert second["context_source"] == "deterministic"
    assert second["context_preamble"].startswith("Document « Architecture Atlas (C2) »")
    # Indexed with the chunk: BM25 on the preamble only (« comité » is not in the preamble, NOVA is).
    found = await opensearch.get_documents("chunks", [first["id"]])
    assert LLM_PREAMBLE in str(found)

    # Provider failure → deterministic fallback.
    llm.use_transport(httpx.MockTransport(lambda _r: httpx.Response(500, json={})))
    c3 = await _text(
        admin_client, slug, title="Architecture Atlas v3", content=ARCHI + " Révision.", classification=1
    )
    await drain()
    third = (await _chunks(admin_client, slug, c3["id"]))[0]
    assert third["context_source"] == "deterministic"


async def test_progressive_contextual_reindex(
    admin_client: httpx.AsyncClient, project: dict[str, Any], db_session: AsyncSession
) -> None:
    slug = str(project["slug"])
    doc = await _text(admin_client, slug, title="Journal Atlas", content=ARCHI)
    await drain()
    project_id = uuid.UUID(str(project["id"]))
    await db_session.execute(
        update(Chunk).where(Chunk.project_id == project_id).values(context_preamble=None, context_source=None)
    )
    await db_session.commit()
    assert await pipeline.schedule_contextual_reindex(db_session) >= 1
    await db_session.commit()
    assert await pipeline.schedule_contextual_reindex(db_session) == 0  # one pending job per project
    await db_session.commit()
    await drain()
    chunks = await _chunks(admin_client, slug, doc["id"])
    assert chunks and all(c["context_source"] == "deterministic" for c in chunks)
    indexed = await opensearch.get_documents("chunks", [chunks[0]["id"]])
    assert "Journal Atlas" in str(indexed)
