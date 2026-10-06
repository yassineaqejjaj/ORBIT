"""Chantier B — retrieval (docs/AI_CONTEXT_ENGINEERING.md §B), without any real network call.

Fake LLM through ``httpx.MockTransport``, hash embeddings (conftest), stub cross-encoder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import settings
from app.context import rerank
from app.enums import CandidateType
from app.governance.policy import Candidate
from app.search import reranker_models

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
