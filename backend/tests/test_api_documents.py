"""Sources / documents / jobs / search API against the test infrastructure (hash embeddings).

Jobs are processed in-process with :class:`app.worker.Worker` (the shared worker service uses another
database). ``extract_memory`` follow-up jobs are left queued: memory extraction is tested elsewhere.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy import select

from app.db import get_sessionmaker
from app.enums import ChunkStatus, JobKind
from app.ingestion.queue import claim_next_job
from app.models import Chunk, Tombstone
from app.search import opensearch
from app.worker import Worker
from tests.conftest import UserInfo

API = "/api/v1/projects"
PIPELINE_KINDS = (JobKind.ingest, JobKind.reindex, JobKind.forget)


async def drain() -> int:
    """Run every queued ingest / reindex / forget job; returns the number processed."""
    worker = Worker(concurrency=1, worker_id="test-ingestion")
    processed = 0
    for _ in range(200):
        async with get_sessionmaker()() as session:
            job = await claim_next_job(session, worker.worker_id, kinds=PIPELINE_KINDS)
        if job is None:
            break
        await worker._process(job.id)
        processed += 1
    return processed


async def _member(
    admin_client: httpx.AsyncClient,
    slug: str,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
    role: str,
    clearance: int,
) -> tuple[UserInfo, httpx.AsyncClient]:
    user = await make_user(clearance=clearance)
    added = await admin_client.post(f"{API}/{slug}/members", json={"email": user.email, "role": role})
    assert added.status_code in (200, 201), added.text
    return user, await client_for(user)


async def _text(client: httpx.AsyncClient, slug: str, **body: object) -> dict:  # type: ignore[type-arg]
    response = await client.post(f"{API}/{slug}/documents/text", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _search(client: httpx.AsyncClient, slug: str, q: str) -> list[dict]:  # type: ignore[type-arg]
    response = await client.get(f"{API}/{slug}/search", params={"q": q, "limit": 50})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
async def team(
    admin_client: httpx.AsyncClient,
    project: dict,  # type: ignore[type-arg]
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> dict[str, object]:
    slug = str(project["slug"])
    editor, editor_client = await _member(admin_client, slug, make_user, client_for, "editor", 2)
    viewer, viewer_client = await _member(admin_client, slug, make_user, client_for, "viewer", 1)
    return {
        "slug": slug,
        "editor": editor,
        "editor_client": editor_client,
        "viewer": viewer,
        "viewer_client": viewer_client,
    }


# --- Ingestion + visibility ----------------------------------------------------------------------------


async def test_text_ingest_visibility_and_search(admin_client: httpx.AsyncClient, team: dict) -> None:  # type: ignore[type-arg]
    slug, editor, viewer = team["slug"], team["editor_client"], team["viewer_client"]
    public = await _text(
        editor,
        slug,
        title="Architecture du portail",
        content="# Architecture\n\nLe portail client s'appuie sur Keycloak pour l'authentification unique.",
        source_kind="document",
        tags=["architecture"],
    )
    restricted = await _text(
        editor,
        slug,
        title="Plan de migration Keycloak (équipe cœur)",
        content="La migration Keycloak vers la version 26 est réservée aux éditeurs.",
        acl_principals=["role:editor"],
    )
    secret = await _text(
        editor, slug, title="Budget Keycloak", content="Licences Keycloak : 12 000 euros.", classification=2
    )
    assert public["status"] == "pending"
    assert public["source_name"] == "Documents" and public["source_kind"] == "document"
    assert restricted["source_name"] == "Notes"  # default kind of the text endpoint
    assert await drain() >= 3

    detail = (await editor.get(f"{API}/{slug}/documents/{public['id']}")).json()
    assert detail["status"] == "indexed", detail
    assert detail["chunk_count"] >= 1 and detail["chunks"]
    ingest_job = next(j for j in detail["jobs"] if j["kind"] == "ingest")  # extract_memory is chained
    assert [s["name"] for s in ingest_job["steps"]][:7] == [
        "extract",
        "pii",
        "classify",
        "chunk",
        "contextualize",
        "embed",
        "index",
    ]
    assert detail["versions"][0]["version"] == 1

    secret_detail = (await editor.get(f"{API}/{slug}/documents/{secret['id']}")).json()
    assert secret_detail["classification"] == 2

    viewer_list = (await viewer.get(f"{API}/{slug}/documents")).json()
    visible_ids = {d["id"] for d in viewer_list["items"]}
    assert public["id"] in visible_ids
    assert restricted["id"] not in visible_ids and secret["id"] not in visible_ids
    assert viewer_list["total"] == len(visible_ids)
    assert (await viewer.get(f"{API}/{slug}/documents/{restricted['id']}")).status_code == 404
    assert (await viewer.get(f"{API}/{slug}/documents/{secret['id']}")).status_code == 404

    viewer_hits = {h["document_id"] for h in await _search(viewer, slug, "Keycloak")}
    assert viewer_hits == {public["id"]}
    editor_hits = {h["document_id"] for h in await _search(editor, slug, "Keycloak")}
    assert {public["id"], restricted["id"], secret["id"]} <= editor_hits
    hit = (await _search(editor, slug, "authentification unique portail"))[0]
    assert hit["document_id"] == public["id"]
    assert hit["document_title"] == "Architecture du portail"
    assert 0 < hit["score"] <= 1

    sources = (await viewer.get(f"{API}/{slug}/sources")).json()
    counts = {s["name"]: s["counts"] for s in sources}
    assert counts["Documents"]["documents"] == 1 and counts["Documents"]["indexed"] == 1
    assert counts["Notes"]["documents"] == 0  # both notes are invisible to the viewer

    jobs = (await viewer.get(f"{API}/{slug}/jobs")).json()
    assert {j["document_id"] for j in jobs["items"]} == {public["id"]}
    assert jobs["items"][0]["document_title"] == "Architecture du portail"

    filtered = (
        await editor.get(f"{API}/{slug}/documents", params={"q": "keycloak", "classification": 2})
    ).json()
    assert [d["id"] for d in filtered["items"]] == [secret["id"]]


async def test_pii_hidden_below_editor(team: dict) -> None:  # type: ignore[type-arg]
    slug, editor, viewer = team["slug"], team["editor_client"], team["viewer_client"]
    doc = await _text(
        editor,
        slug,
        title="Compte rendu client",
        content="Contact : Mme Claire Dubois, claire.dubois@exemple.fr, 06 12 34 56 78.",
        classification=1,
    )
    await drain()
    for_editor = (await editor.get(f"{API}/{slug}/documents/{doc['id']}")).json()
    assert for_editor["pii_count"] >= 3
    chunk = for_editor["chunks"][0]
    assert any(p["text"] == "claire.dubois@exemple.fr" for p in chunk["pii"])
    assert "[EMAIL]" in chunk["text_redacted"]

    for_viewer = (await viewer.get(f"{API}/{slug}/documents/{doc['id']}")).json()
    viewer_chunk = for_viewer["chunks"][0]
    assert all(p.get("text") is None for p in viewer_chunk["pii"])
    assert "claire.dubois@exemple.fr" not in viewer_chunk["text"]
    hits = await _search(viewer, slug, "Compte rendu client Claire")
    assert hits and all("claire.dubois@exemple.fr" not in h["text"] for h in hits)


async def test_upload_versions_raw_and_supersession(team: dict) -> None:  # type: ignore[type-arg]
    slug, editor = team["slug"], team["editor_client"]
    v1 = b"# Specification\n\nLe module de facturation exporte en PDF chaque nuit."
    uploaded = await editor.post(
        f"{API}/{slug}/documents/upload",
        files=[("files", ("specification_facturation.md", v1, "text/markdown"))],
        data={"tags": "facturation, specs", "acl_principals": "project:*"},
    )
    assert uploaded.status_code == 201, uploaded.text
    [doc] = uploaded.json()
    assert doc["title"] == "specification facturation"
    assert doc["tags"] == ["facturation", "specs"]
    await drain()

    same = await editor.post(
        f"{API}/{slug}/documents/upload",
        files=[("files", ("specification_facturation.md", v1, "text/markdown"))],
    )
    assert same.json()[0]["current_version"] == 1  # identical content: no new version

    v2 = b"# Specification\n\nLe module de facturation exporte en CSV toutes les heures."
    second = await editor.post(
        f"{API}/{slug}/documents/upload",
        files=[("files", ("specification_facturation.md", v2, "text/markdown"))],
    )
    assert second.status_code == 201
    assert second.json()[0]["id"] == doc["id"]
    assert second.json()[0]["current_version"] == 2
    await drain()

    detail = (await editor.get(f"{API}/{slug}/documents/{doc['id']}")).json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert all(c["version"] == 2 for c in detail["chunks"])
    async with get_sessionmaker()() as session:
        old = list(
            await session.scalars(
                select(Chunk).where(Chunk.document_id == uuid.UUID(doc["id"]), Chunk.version == 1)
            )
        )
    assert old and all(c.status == ChunkStatus.superseded for c in old)
    hits = [h for h in await _search(editor, slug, "facturation exporte") if h["document_id"] == doc["id"]]
    assert hits and all("CSV" in h["text"] for h in hits)

    raw = await editor.get(f"{API}/{slug}/documents/{doc['id']}/raw")
    assert raw.status_code == 200
    assert raw.content == v2
    assert "attachment" in raw.headers["content-disposition"]

    unsupported = await editor.post(
        f"{API}/{slug}/documents/upload", files=[("files", ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png"))]
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "validation_error"


async def test_import_tickets_then_update(team: dict) -> None:  # type: ignore[type-arg]
    slug, editor = team["slug"], team["editor_client"]
    tickets = [
        {
            "id": "SUP-1",
            "subject": "Export PDF en échec",
            "description": "Erreur 500 à l'export.",
            "priority": "haute",
        },
        {"id": "SUP-2", "subject": "Lenteur recherche", "description": "La recherche prend 8 secondes."},
    ]
    first = await editor.post(
        f"{API}/{slug}/documents/import",
        files={"file": ("tickets.json", json.dumps(tickets).encode(), "application/json")},
        data={"source_kind": "ticket"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 2 and first.json()["updated"] == 0
    assert {d["source_name"] for d in first.json()["documents"]} == {"Tickets"}
    assert {d["external_id"] for d in first.json()["documents"]} == {"SUP-1", "SUP-2"}

    tickets[1]["description"] = "La recherche prend 2 secondes après correctif."
    second = await editor.post(
        f"{API}/{slug}/documents/import",
        files={"file": ("tickets.json", json.dumps(tickets).encode(), "application/json")},
        data={"source_kind": "ticket"},
    )
    assert second.json()["created"] == 0 and second.json()["updated"] == 1

    bad = await editor.post(
        f"{API}/{slug}/documents/import",
        files={"file": ("tickets.json", b"{oops", "application/json")},
        data={"source_kind": "ticket"},
    )
    assert bad.status_code == 422


async def test_patch_acl_takes_effect_immediately(admin_client: httpx.AsyncClient, team: dict) -> None:  # type: ignore[type-arg]
    slug, editor, viewer = team["slug"], team["editor_client"], team["viewer_client"]
    doc = await _text(
        editor, slug, title="Roadmap mobile", content="La roadmap mobile prévoit le mode hors ligne."
    )
    await drain()
    assert any(
        h["document_id"] == doc["id"] for h in await _search(viewer, slug, "roadmap mobile hors ligne")
    )

    patched = await editor.patch(
        f"{API}/{slug}/documents/{doc['id']}", json={"acl_principals": ["role:editor"], "tags": ["mobile"]}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["acl_principals"] == ["role:editor"]
    assert not any(
        h["document_id"] == doc["id"] for h in await _search(viewer, slug, "roadmap mobile hors ligne")
    )
    assert (await viewer.get(f"{API}/{slug}/documents/{doc['id']}")).status_code == 404
    assert (await viewer.patch(f"{API}/{slug}/documents/{doc['id']}", json={"title": "x"})).status_code == 403

    audit = (await admin_client.get(f"{API}/{slug}/audit", params={"action": "governance"})).json()
    items = audit["items"] if isinstance(audit, dict) else audit
    assert any(e["target_id"] == doc["id"] for e in items)


async def test_reprocess_and_forget(admin_client: httpx.AsyncClient, team: dict) -> None:  # type: ignore[type-arg]
    slug, editor = team["slug"], team["editor_client"]
    doc = await _text(
        editor, slug, title="Contrat fournisseur", content="Le contrat fournisseur expire en juin."
    )
    await drain()

    job = await editor.post(f"{API}/{slug}/documents/{doc['id']}/reprocess")
    assert job.status_code == 200, job.text
    assert job.json()["kind"] == "ingest" and job.json()["status"] == "queued"
    await drain()

    assert (
        await editor.post(f"{API}/{slug}/documents/{doc['id']}/forget", json={"reason": "RGPD"})
    ).status_code == 403
    forgotten = await admin_client.post(
        f"{API}/{slug}/documents/{doc['id']}/forget", json={"reason": "Demande d'effacement RGPD"}
    )
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten.json()["status"] == "forgotten"
    assert not any(
        h["document_id"] == doc["id"] for h in await _search(editor, slug, "contrat fournisseur juin")
    )
    await drain()

    detail = (await admin_client.get(f"{API}/{slug}/documents/{doc['id']}")).json()
    assert detail["status"] == "forgotten" and detail["forgotten_at"]
    assert all(c["text"] == "[oublié]" and c["status"] == "forgotten" for c in detail["chunks"])
    assert (await admin_client.get(f"{API}/{slug}/documents/{doc['id']}/raw")).status_code == 404
    assert (
        await admin_client.post(f"{API}/{slug}/documents/{doc['id']}/forget", json={"reason": "bis"})
    ).status_code == 409
    remaining = await opensearch.count("chunks", filters={"document_id": doc["id"]})
    assert remaining == 0
    async with get_sessionmaker()() as session:
        tombstone = await session.scalar(select(Tombstone).where(Tombstone.target_id == uuid.UUID(doc["id"])))
    assert tombstone is not None and tombstone.reason == "Demande d'effacement RGPD"


async def test_sources_crud_and_agent_push(
    admin_client: httpx.AsyncClient,
    team: dict,  # type: ignore[type-arg]
    agent_client: Callable[..., httpx.AsyncClient],
) -> None:
    slug, editor, viewer = team["slug"], team["editor_client"], team["viewer_client"]
    created = await editor.post(
        f"{API}/{slug}/sources",
        json={"name": "Confluence produit", "kind": "document", "default_classification": 2},
    )
    assert created.status_code == 201, created.text
    source = created.json()
    assert source["counts"] == {"documents": 0, "indexed": 0, "failed": 0, "processing": 0}
    assert (
        await editor.post(f"{API}/{slug}/sources", json={"name": "confluence produit", "kind": "note"})
    ).status_code == 409
    assert (await viewer.post(f"{API}/{slug}/sources", json={"name": "X", "kind": "note"})).status_code == 403
    patched = await editor.patch(
        f"{API}/{slug}/sources/{source['id']}", json={"description": "Espace produit"}
    )
    assert patched.status_code == 200 and patched.json()["description"] == "Espace produit"
    assert (
        await editor.patch(f"{API}/{slug}/sources/{uuid.uuid4()}", json={"description": "x"})
    ).status_code == 404

    in_source = await _text(editor, slug, title="Charte produit", content="Charte.", source_id=source["id"])
    assert in_source["classification"] == 2  # source default

    agent = await admin_client.post(
        f"{API}/{slug}/agents", json={"name": "Agent support", "kind": "custom", "clearance": 1}
    )
    assert agent.status_code == 201, agent.text
    bot = agent_client(agent.json()["api_key"])
    pushed = await bot.post(
        f"{API}/{slug}/documents/text",
        json={
            "title": "Trace session 42",
            "content": "L'agent a résolu le ticket SUP-9.",
            "source_kind": "agent_trace",
        },
    )
    assert pushed.status_code == 201, pushed.text
    assert pushed.json()["source_name"] == "Traces agents"
    assert (await bot.get(f"{API}/{slug}/documents")).status_code == 403
