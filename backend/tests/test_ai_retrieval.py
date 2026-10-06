"""Chantier B — retrieval (docs/AI_CONTEXT_ENGINEERING.md §B), without any real network call.

Fake LLM through ``httpx.MockTransport``, hash embeddings (conftest), stub cross-encoder.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.context import query_rewrite, rerank
from app.enums import CandidateType
from app.governance.policy import Candidate
from app.ingestion import contextual, pipeline, visual
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


# --- B3: query rewriting -------------------------------------------------------------------------------

LONG_TASK = (
    "Prépare la revue de lancement : résume la décision sur la base de données du service Atlas ; "
    "liste les risques de sécurité du portail client puis donne le planning de mise en production"
)


def test_deterministic_decomposition_and_expansion() -> None:
    subtopics = query_rewrite.decompose(LONG_TASK)
    assert 2 <= len(subtopics) <= query_rewrite.MAX_SUBTOPICS
    assert any("risques" in s for s in subtopics) and any("planning" in s for s in subtopics)
    assert query_rewrite.decompose("Quelle base de données ?") == []

    aliases = query_rewrite.aliases_from_titles(["Note de cadrage Plateforme Atlas Facturation (PAF)"])
    assert "Plateforme Atlas Facturation" in query_rewrite.expansion_terms("Où en est la PAF ?", aliases)
    assert "PAF" in query_rewrite.expansion_terms("Statut de la plateforme atlas facturation", aliases)
    terms = query_rewrite.expansion_terms("Date de la MEP et choix de la BDD", {})
    assert "mise en production" in terms and "base de données" in terms
    rewrite = query_rewrite.deterministic_rewrite("Date de la MEP", {})
    assert rewrite.method == "deterministic"
    assert (
        rewrite.queries[0].kind == query_rewrite.KIND_EXPANSION
        and "mise en production" in rewrite.queries[0].text
    )

    texts = ["Décision : PostgreSQL retenu pour la base de données du service Atlas."]
    missing = query_rewrite.uncovered(subtopics, texts)
    assert missing and all("base de données" not in m for m in missing)


async def test_llm_rewrite_multi_query_hyde_and_guardrail(
    db_session: AsyncSession,
    project: dict[str, Any],
    fake_llm: Callable[..., FakeLLM],  # noqa: F811
) -> None:
    def reply(_prompt: str) -> str:
        return json.dumps(
            {
                "reformulations": ["choix SGBD Atlas", "base de données retenue Atlas"],
                "sous_questions": ["Quelle base de données ?", "Quels risques de sécurité ?"],
                "reponse_hypothetique": "Le comité a retenu PostgreSQL pour Atlas.",
            }
        )

    fake = fake_llm(reply, provider="openai", query_rewrite="auto")
    project_id = uuid.UUID(str(project["id"]))
    result = await query_rewrite.rewrite(db_session, project_id, "Quelle base pour Atlas et quels risques ?")
    assert result.method == "llm"
    kinds = [q.kind for q in result.queries]
    assert kinds.count(query_rewrite.KIND_MULTI) == 2 and query_rewrite.KIND_HYDE in kinds
    assert result.subtopics == ["Quelle base de données ?", "Quels risques de sécurité ?"]
    sent = len(fake.requests)

    secret_task = "Strictement confidentiel : quel est le budget de la fusion Orion ?"
    assert query_rewrite.task_level(secret_task) >= 2
    skips = guardrail.skip_count()
    blocked = await query_rewrite.rewrite(db_session, project_id, secret_task)
    assert len(fake.requests) == sent  # nothing sent above the ceiling
    assert blocked.method == "deterministic" and blocked.note and "Garde-fou" in blocked.note
    assert guardrail.skip_count() == skips + 1

    llm.use_transport(httpx.MockTransport(lambda _r: httpx.Response(503, json={})))
    failed = await query_rewrite.rewrite(db_session, project_id, "Quelle base pour Atlas ?")
    assert failed.method == "deterministic"


# --- B4: iterative retrieval ---------------------------------------------------------------------------


async def test_iterative_rounds_bounded_and_traced(
    admin_client: httpx.AsyncClient, project: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.context import retrieval

    slug = str(project["slug"])
    await _text(admin_client, slug, title="Décision base Atlas", content=ARCHI)
    await _text(
        admin_client,
        slug,
        title="Risques portail",
        content="Risque de sécurité : le portail client expose une API sans limitation de débit.",
    )
    await drain()

    async def _post(task: str) -> dict[str, Any]:
        response = await admin_client.post(f"{API}/{slug}/context", json={"task": task, "min_relevance": 0.0})
        assert response.status_code == 200, response.text
        return response.json()

    package = await _post(LONG_TASK)
    rounds = package["timings"]["rounds"]
    assert 1 <= len(rounds) <= 3 and rounds[0]["round"] == 1 and rounds[0]["queries"][0]["kind"] == "task"
    assert all(r["ms"] >= 0 for r in rounds)

    # Nothing ever covers the sub-topics and every round finds something: the loop stops at 3 rounds.
    real_search_more = retrieval.search_more

    async def always_new(*args: Any, **kwargs: Any) -> int:
        return await real_search_more(*args, **kwargs) + 1

    monkeypatch.setattr(retrieval, "coverage_texts", lambda _raw, limit=40: [])
    monkeypatch.setattr(retrieval, "search_more", always_new)
    rounds = (await _post(LONG_TASK))["timings"]["rounds"]
    assert [r["round"] for r in rounds] == [1, 2, 3]
    assert all(q["kind"] == "subtopic" for r in rounds[1:] for q in r["queries"])
    assert rounds[-1]["uncovered"]

    monkeypatch.setattr(settings, "retrieval_max_rounds", 1)
    assert len((await _post(LONG_TASK))["timings"]["rounds"]) == 1


# --- B5: visual documents ------------------------------------------------------------------------------

DIAGRAM_ALT = "Schéma d'architecture Atlas : API, file Kafka et base PostgreSQL"
VISION_ANSWER = "Schéma montrant le service Atlas Facturation relié à PostgreSQL et à la file Kafka NOVA."


def _png(width: int, height: int) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(image).rectangle((10, 10, width - 10, height - 10), outline="navy", width=4)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _pdf_with_image() -> bytes:
    from PIL import Image
    from pypdf import PdfReader, PdfWriter

    from tests.test_ingestion_units import _minimal_pdf

    image_pdf = io.BytesIO()
    Image.open(io.BytesIO(_png(320, 200))).save(image_pdf, format="PDF")
    writer = PdfWriter()
    for blob in (
        _minimal_pdf(["Dossier d'architecture Atlas", "Voir le schema ci-dessous."]),
        image_pdf.getvalue(),
    ):
        for page in PdfReader(io.BytesIO(blob)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _pptx_with_images() -> bytes:
    pic = (
        '<p:pic><p:nvPicPr><p:cNvPr id="{id}" name="Image {id}" descr="{descr}"/></p:nvPicPr>'
        '<p:blipFill><a:blip r:embed="{rid}"/></p:blipFill></p:pic>'
    )
    slide = (
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree>'
        + pic.format(id=2, descr=DIAGRAM_ALT, rid="rId2")
        + pic.format(id=3, descr="logo", rid="rId3")
        + "</p:spTree></p:cSld></p:sld>"
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId2" Type="image" Target="../media/image1.png"/>'
        '<Relationship Id="rId3" Type="image" Target="../media/logo.png"/></Relationships>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
        archive.writestr("ppt/media/image1.png", _png(400, 240))
        archive.writestr("ppt/media/logo.png", _png(24, 24))
    return out.getvalue()


@pytest.fixture
def no_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(visual, "_ocr_checked", True)
    monkeypatch.setattr(visual, "_ocr_engine", None)


def test_extract_images_pdf_and_pptx() -> None:
    [pdf_image] = visual.extract_images(_pdf_with_image(), visual.PDF, "archi.pdf")
    assert (
        pdf_image.locator == "page 2"
        and pdf_image.width == 320
        and pdf_image.mime_type in {"image/png", "image/jpeg"}
    )
    items = visual.extract_images(_pptx_with_images(), visual.PPTX, "atlas.pptx")
    assert [(i.locator, i.alt) for i in items] == [("diapositive 1", DIAGRAM_ALT)]  # 24 px logo ignored
    assert visual.extract_images(b"# texte", "text/markdown", "a.md") == []


async def test_describe_vision_guardrail_ocr_and_alt(
    fake_llm: Callable[..., FakeLLM],  # noqa: F811
    no_ocr: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = fake_llm(lambda _p: VISION_ANSWER)  # Anthropic Messages API
    pptx = visual.extract_images(_pptx_with_images(), visual.PPTX, "atlas.pptx")
    pdf = visual.extract_images(_pdf_with_image(), visual.PDF, "archi.pdf")

    [described] = await visual.describe(pptx, classification=1)
    assert described.method == visual.METHOD_LLM and described.text == VISION_ANSWER
    content = fake.bodies()[-1]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    assert DIAGRAM_ALT in content[-1]["text"]

    sent = len(fake.requests)
    restricted = await visual.describe(pptx + pdf, classification=2)
    assert len(fake.requests) == sent  # C2 images never sent to the external LLM
    assert [(d.method, d.text) for d in restricted] == [
        (visual.METHOD_ALT, DIAGRAM_ALT)
    ]  # no alt, no OCR: dropped

    monkeypatch.setattr(visual, "_ocr_engine", lambda _data: "API  Kafka   PostgreSQL")
    ocr = await visual.describe(pdf, classification=3)
    assert ocr[0].method == visual.METHOD_OCR and "Texte de l'image : API Kafka PostgreSQL" in ocr[0].text
    markdown = visual.to_markdown(restricted + ocr)
    assert markdown.startswith("## Éléments visuels") and "### Image — page 2" in markdown


async def test_visual_chunks_indexed(
    admin_client: httpx.AsyncClient,
    project: dict[str, Any],
    fake_llm: Callable[..., FakeLLM],  # noqa: F811
    no_ocr: None,
) -> None:
    slug = str(project["slug"])
    fake_llm(lambda p: VISION_ANSWER if "Décris-la" in str(p) else "{}")
    uploaded = await admin_client.post(
        f"{API}/{slug}/documents/upload",
        files=[("files", ("archi.pdf", _pdf_with_image(), "application/pdf"))],
    )
    assert uploaded.status_code == 201, uploaded.text
    [doc] = uploaded.json()
    await drain()
    detail = (await admin_client.get(f"{API}/{slug}/documents/{doc['id']}")).json()
    assert detail["status"] == "indexed", detail
    visual_chunks = [c for c in detail["chunks"] if VISION_ANSWER in c["text"]]
    assert visual_chunks and "## Éléments visuels\n\n### Image — page 2" in visual_chunks[0]["text"]
    job = next(j for j in detail["jobs"] if j["kind"] == "ingest")
    step = next(s for s in job["steps"] if s["name"] == "visual")
    assert "1 image(s) · 1 décrite(s) (1 LLM vision)" in step["detail"]
    hits = (await admin_client.get(f"{API}/{slug}/search", params={"q": "file Kafka NOVA"})).json()
    assert any(
        h.get("chunk_id") == visual_chunks[0]["id"] or h.get("id") == visual_chunks[0]["id"] for h in hits
    )
