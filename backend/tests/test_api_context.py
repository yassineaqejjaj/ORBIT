"""End-to-end tests of the context engine through the REST API.

Retrieval is forced onto the Postgres full-text fallback so the tests only depend on rows seeded
here (the hybrid index is owned by another module and may be empty for this project).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import retrieval
from app.enums import (
    ActorType,
    ChunkStatus,
    DocumentStatus,
    MemoryEventType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RelationNodeType,
    RelationType,
    SourceKind,
)
from app.models import (
    AuditLog,
    Chunk,
    ContextDecision,
    ContextRequest,
    Document,
    MemoryEvent,
    MemoryItem,
    Relation,
    Source,
)
from tests.conftest import UserInfo

pytestmark = pytest.mark.asyncio

TASK = "Quelle méthode d'authentification retenir pour Atlas ?"
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _fulltext_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unavailable(*_args: Any, **_kwargs: Any) -> list[retrieval.IndexHit]:
        raise retrieval.RetrievalUnavailable("tests: index désactivé")

    monkeypatch.setattr(retrieval, "search_index", _unavailable)


@dataclass
class Seed:
    project_id: uuid.UUID
    slug: str
    ids: dict[str, uuid.UUID] = field(default_factory=dict)


def _chunk(project_id: uuid.UUID, document: Document, text: str, **kwargs: Any) -> Chunk:
    return Chunk(
        project_id=project_id,
        document_id=document.id,
        version=kwargs.pop("version", document.current_version),
        ordinal=kwargs.pop("ordinal", 0),
        text=text,
        text_redacted=kwargs.pop("text_redacted", text),
        token_count=len(text.split()),
        classification=document.classification,
        acl_principals=list(document.acl_principals),
        **kwargs,
    )


async def seed_project(session: AsyncSession, project: dict[str, Any], other_user: uuid.UUID) -> Seed:
    project_id = uuid.UUID(str(project["id"]))
    seed = Seed(project_id=project_id, slug=str(project["slug"]))
    docs_source = Source(project_id=project_id, name="Spécifications", kind=SourceKind.document)
    tickets_source = Source(project_id=project_id, name="Support", kind=SourceKind.ticket)
    session.add_all([docs_source, tickets_source])
    await session.flush()

    def document(title: str, source: Source = docs_source, **kwargs: Any) -> Document:
        doc = Document(
            project_id=project_id,
            source_id=source.id,
            title=title,
            uri=kwargs.pop("uri", f"https://wiki.example/{uuid.uuid4().hex[:6]}"),
            status=kwargs.pop("status", DocumentStatus.indexed),
            source_updated_at=kwargs.pop("source_updated_at", NOW - timedelta(days=10)),
            **kwargs,
        )
        session.add(doc)
        return doc

    spec = document("Spécification Atlas", current_version=2, uri="https://wiki.example/atlas")
    copy = document("Copie de la spécification Atlas")
    secret = document("Audit de sécurité Atlas", classification=3)
    board = document("Note de direction Atlas", acl_principals=["role:owner"])
    ticket = document("Ticket support Atlas", tickets_source, source_updated_at=NOW - timedelta(days=200))
    forgotten = document(
        "Ancien export Atlas", status=DocumentStatus.forgotten, forgotten_at=NOW - timedelta(days=1)
    )
    await session.flush()

    spec_text = (
        "L'authentification Atlas repose sur OIDC avec le fournisseur d'identité interne. "
        "Les sessions Atlas expirent après trente minutes d'inactivité."
    )
    chunks = {
        "spec": _chunk(project_id, spec, spec_text, section="Authentification"),
        "spec_v1": _chunk(
            project_id,
            spec,
            "Version 1 : l'authentification Atlas utilise des mots de passe locaux.",
            version=1,
            status=ChunkStatus.superseded,
        ),
        "copy": _chunk(project_id, copy, spec_text),
        "secret": _chunk(project_id, secret, "Faille critique d'authentification Atlas relevée par l'audit."),
        "board": _chunk(project_id, board, "La direction valide le budget d'authentification Atlas."),
        "ticket": _chunk(project_id, ticket, "Incident d'authentification Atlas sur le portail client."),
        "forgotten": _chunk(
            project_id, forgotten, "Export d'authentification Atlas.", status=ChunkStatus.forgotten
        ),
    }
    session.add_all(chunks.values())

    def memory(title: str, content: str, **kwargs: Any) -> MemoryItem:
        item = MemoryItem(
            project_id=project_id,
            lineage_id=uuid.uuid4(),
            scope=kwargs.pop("scope", MemoryScope.project),
            kind=kwargs.pop("kind", MemoryKind.decision),
            status=kwargs.pop("status", MemoryStatus.validated),
            title=title,
            content=content,
            confidence=kwargs.pop("confidence", 0.9),
            valid_from=kwargs.pop("valid_from", NOW - timedelta(days=5)),
            created_by_type=ActorType.system,
            **kwargs,
        )
        session.add(item)
        return item

    decision = memory(
        "Authentification Atlas via OIDC",
        "Décision : l'authentification Atlas passe par OIDC avec le fournisseur d'identité interne.",
        valid_from=NOW - timedelta(days=400),  # validated decisions are never stale
    )
    proposed = memory(
        "Authentification Atlas par mot de passe",
        "Proposition : conserver une authentification Atlas par mot de passe local.",
        status=MemoryStatus.proposed,
        confidence=0.6,
    )
    old_rule = memory(
        "Ancienne règle d'authentification Atlas",
        "Règle : l'authentification Atlas utilise le LDAP historique.",
        kind=MemoryKind.constraint,
        status=MemoryStatus.superseded,
    )
    personal = memory(
        "Préférence d'authentification Atlas de Bob",
        "Bob préfère l'authentification Atlas par clé matérielle.",
        scope=MemoryScope.user,
        kind=MemoryKind.preference,
        subject_user_id=other_user,
        acl_principals=[f"user:{other_user}"],
    )
    expired = memory(
        "Brouillon de session sur l'authentification Atlas",
        "Note temporaire : tester l'authentification Atlas en préproduction.",
        scope=MemoryScope.short_term,
        kind=MemoryKind.fact,
        status=MemoryStatus.proposed,
        session_id="sess-1",
        expires_at=NOW - timedelta(hours=2),
    )
    await session.flush()
    old_rule.superseded_by_id = decision.id
    session.add_all(
        [
            Relation(
                project_id=project_id,
                src_type=RelationNodeType.memory,
                src_id=proposed.id,
                rel_type=RelationType.contradicts,
                dst_type=RelationNodeType.memory,
                dst_id=decision.id,
                confidence=0.9,
            ),
            Relation(
                project_id=project_id,
                src_type=RelationNodeType.memory,
                src_id=decision.id,
                rel_type=RelationType.supersedes,
                dst_type=RelationNodeType.memory,
                dst_id=old_rule.id,
            ),
        ]
    )
    await session.commit()
    seed.ids.update({f"chunk_{k}": c.id for k, c in chunks.items()})
    seed.ids.update(
        decision=decision.id,
        decision_lineage=decision.lineage_id,
        proposed=proposed.id,
        old_rule=old_rule.id,
        personal=personal.id,
        expired=expired.id,
    )
    return seed


async def add_member(admin: httpx.AsyncClient, slug: str, user: UserInfo, role: str = "viewer") -> None:
    response = await admin.post(f"/api/v1/projects/{slug}/members", json={"email": user.email, "role": role})
    assert response.status_code in (200, 201), response.text


@pytest.fixture
async def world(
    admin_client: httpx.AsyncClient,
    project: dict[str, Any],
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
    db_session: AsyncSession,
) -> dict[str, Any]:
    viewer = await make_user(clearance=1, name="Vera Viewer")
    bob = await make_user(clearance=1, name="Bob Membre")
    await add_member(admin_client, str(project["slug"]), viewer)
    await add_member(admin_client, str(project["slug"]), bob)
    seed = await seed_project(db_session, project, bob.id)
    return {"seed": seed, "viewer": viewer, "viewer_client": await client_for(viewer), "bob": bob}


def _by_code(package: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [e for e in package["excluded"] if e["reason_code"] == code]


def _ids(entries: list[dict[str, Any]]) -> set[str]:
    return {str(e.get("id")) for e in entries}


async def _post(client: httpx.AsyncClient, slug: str, **body: Any) -> dict[str, Any]:
    response = await client.post(f"/api/v1/projects/{slug}/context", json={"task": TASK, **body})
    assert response.status_code == 200, response.text
    return response.json()


async def test_governed_package_for_viewer(world: dict[str, Any], db_session: AsyncSession) -> None:
    seed: Seed = world["seed"]
    ids = seed.ids
    package = await _post(world["viewer_client"], seed.slug, min_relevance=0.0)

    # Shape of the contract.
    assert set(package["timings"]) == {
        "understand",
        "rewrite",
        "retrieve",
        "fuse",
        "rerank",
        "govern",
        "select",
        "compress",
        "package",
        "total",
        "rounds",
    }
    assert package["timings"]["rounds"][0]["round"] == 1
    assert package["config"]["retrieval"].startswith("hybrid-bm25-knn-rrf-v1")
    assert package["tokens_used"] <= package["token_budget"] == 4000
    assert package["candidates_count"] == len(package["items"]) + len(package["excluded"])

    # Citations S1..Sn in presentation order, each cited in the Markdown and listed in the sources.
    citations = [item["citation"] for item in package["items"]]
    assert citations == [f"S{i}" for i in range(1, len(citations) + 1)]
    assert "## Sources" in package["context"]
    for citation in citations:
        assert f"[{citation}]" in package["context"]

    included = {item["id"] for item in package["items"]}
    assert str(ids["decision"]) in included
    assert str(ids["chunk_spec"]) in included or str(ids["chunk_copy"]) in included
    assert all(item["reason_code"] == "INCLUDED_RELEVANT" for item in package["items"])
    decision_item = next(i for i in package["items"] if i["id"] == str(ids["decision"]))
    assert decision_item["reason_detail"].startswith("score ")

    # Every exclusion reason reachable in this corpus.
    assert _ids(_by_code(package, "EXCLUDED_FORGOTTEN")) == {str(ids["chunk_forgotten"])}
    stale = _by_code(package, "EXCLUDED_STALE")
    assert [e["reason_detail"] for e in stale] == ["200 j > 90 j (tickets)"]
    superseded = _by_code(package, "EXCLUDED_SUPERSEDED")
    assert {str(ids["chunk_spec_v1"]), str(ids["old_rule"])} <= _ids(superseded)
    rule = next(e for e in superseded if e["id"] == str(ids["old_rule"]))
    assert "Authentification Atlas via OIDC" in rule["reason_detail"]
    conflict = _by_code(package, "EXCLUDED_CONFLICT")
    assert str(ids["proposed"]) in _ids(conflict)
    assert "Authentification Atlas via OIDC" in next(
        e["reason_detail"] for e in conflict if e["id"] == str(ids["proposed"])
    )
    duplicates = _by_code(package, "EXCLUDED_DUPLICATE")
    assert len(duplicates) == 1 and duplicates[0]["related_citation"] in citations
    assert len(_by_code(package, "EXCLUDED_EXPIRED")) == 1

    # Non-leak: restricted items are counted but never described to a viewer.
    for code in ("EXCLUDED_ACL", "EXCLUDED_CLASSIFICATION"):
        entries = _by_code(package, code)
        assert len(entries) == 1, code
        assert entries[0]["redacted"] is True
        assert entries[0].get("id") is None and entries[0].get("title") is None
        assert entries[0].get("excerpt") is None
    scope = _by_code(package, "EXCLUDED_SCOPE")
    assert len(scope) == 1 and scope[0]["redacted"] is True and scope[0].get("title") is None
    for secret in ("Audit de sécurité", "Note de direction", "Bob préfère", "Préférence d'authentification"):
        assert secret not in package["context"]
        assert secret not in str(package)
    summary = package["exclusion_summary"]
    assert summary["EXCLUDED_ACL"] == 1 and summary["EXCLUDED_CLASSIFICATION"] == 1

    # Persistence: request row + one decision per candidate.
    request_id = uuid.UUID(package["request_id"])
    row = await db_session.get(ContextRequest, request_id)
    assert row is not None and row.tokens_used == package["tokens_used"]
    count = await db_session.scalar(
        select(func.count()).select_from(ContextDecision).where(ContextDecision.request_id == request_id)
    )
    assert count == package["candidates_count"]
    audit_count = await db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "context.request", AuditLog.target_id == str(request_id))
    )
    assert audit_count == 1


async def test_owner_sees_restricted_details_viewer_does_not(
    world: dict[str, Any], admin_client: httpx.AsyncClient
) -> None:
    seed: Seed = world["seed"]
    viewer_client: httpx.AsyncClient = world["viewer_client"]
    package = await _post(viewer_client, seed.slug, min_relevance=0.0)
    url = f"/api/v1/projects/{seed.slug}/context/requests/{package['request_id']}"

    as_viewer = (await viewer_client.get(url)).json()
    acl = _by_code(as_viewer, "EXCLUDED_ACL")[0]
    assert acl["redacted"] is True and acl.get("title") is None

    response = await admin_client.get(url)
    assert response.status_code == 200, response.text
    as_owner = response.json()
    assert as_owner["context"] == package["context"]
    owner_acl = _by_code(as_owner, "EXCLUDED_ACL")[0]
    assert owner_acl["title"] == "Note de direction Atlas"
    assert owner_acl["reason_detail"] == "réservé à : propriétaires"
    owner_cls = _by_code(as_owner, "EXCLUDED_CLASSIFICATION")[0]
    assert owner_cls["title"] == "Audit de sécurité Atlas"
    assert owner_cls["reason_detail"] == "C3 > habilitation C1"


async def test_admin_gets_classified_content_with_warning(
    world: dict[str, Any], admin_client: httpx.AsyncClient
) -> None:
    seed: Seed = world["seed"]
    package = await _post(admin_client, seed.slug, min_relevance=0.0)
    included = {item["id"] for item in package["items"]}
    assert str(seed.ids["chunk_secret"]) in included
    assert str(seed.ids["chunk_board"]) in included
    assert any("C3" in warning for warning in package["warnings"])
    # The admin is not Bob: Bob's personal memory stays out of scope.
    assert str(seed.ids["personal"]) not in included


async def test_request_options_scope_low_score_and_budget(world: dict[str, Any]) -> None:
    seed: Seed = world["seed"]
    client: httpx.AsyncClient = world["viewer_client"]

    strict = await _post(client, seed.slug, min_relevance=0.99)
    low = _by_code(strict, "EXCLUDED_LOW_SCORE")
    assert low and all("< seuil 0,99" in e["reason_detail"] for e in low)

    no_sources = await _post(client, seed.slug, include_sources=False, min_relevance=0.0)
    assert all(item["candidate_type"] != "chunk" for item in no_sources["items"])

    tickets_only = await _post(client, seed.slug, source_kinds=["ticket"], min_relevance=0.0)
    scoped = [
        e for e in _by_code(tickets_only, "EXCLUDED_SCOPE") if e.get("id") == str(seed.ids["chunk_spec"])
    ]
    assert scoped and scoped[0]["reason_detail"] == "type de source non demandé (documents)"

    fresh = await _post(client, seed.slug, freshness_days=365, min_relevance=0.0)
    assert not _by_code(fresh, "EXCLUDED_STALE")

    small = await _post(client, seed.slug, token_budget=500, min_relevance=0.0)
    assert small["token_budget"] == 500 and small["tokens_used"] <= 500

    too_small = await client.post(
        f"/api/v1/projects/{seed.slug}/context", json={"task": TASK, "token_budget": 100}
    )
    assert too_small.status_code == 422


async def test_agent_gets_counters_only_and_on_behalf_of(
    world: dict[str, Any], admin_client: httpx.AsyncClient, agent_client: Callable[..., httpx.AsyncClient]
) -> None:
    seed: Seed = world["seed"]
    created = await admin_client.post(
        f"/api/v1/projects/{seed.slug}/agents",
        json={"name": "Agent Produit", "kind": "product", "clearance": 2},
    )
    assert created.status_code == 201, created.text
    agent = agent_client(created.json()["api_key"])

    package = await _post(agent, seed.slug, min_relevance=0.0)
    assert package["excluded"] == []
    assert package["exclusion_summary"]
    assert str(seed.ids["chunk_secret"]) not in {i["id"] for i in package["items"]}  # C3 > agent C2

    bob: UserInfo = world["bob"]
    for_bob = await _post(agent, seed.slug, on_behalf_of=str(bob.id), min_relevance=0.0, explain=True)
    assert str(seed.ids["personal"]) in {i["id"] for i in for_bob["items"]}

    stranger = await agent.post(
        f"/api/v1/projects/{seed.slug}/context", json={"task": TASK, "on_behalf_of": str(uuid.uuid4())}
    )
    assert stranger.status_code == 422
    assert stranger.json()["detail"] == "on_behalf_of doit désigner un membre du projet"

    history = await admin_client.get(
        f"/api/v1/projects/{seed.slug}/context/requests", params={"agent_id": created.json()["agent"]["id"]}
    )
    assert history.status_code == 200
    page = history.json()
    assert page["total"] == 2
    assert page["items"][0]["agent"]["name"] == "Agent Produit"

    # Feedback from the agent on its own request.
    first = package["items"][0]["citation"]
    feedback = await agent.post(
        f"/api/v1/projects/{seed.slug}/context/requests/{package['request_id']}/feedback",
        json={"rating": 4, "item_flags": [{"citation": first, "flag": "irrelevant"}]},
    )
    assert feedback.status_code == 200, feedback.text


async def test_feedback_outdated_proposes_obsolescence(
    world: dict[str, Any], admin_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    seed: Seed = world["seed"]
    client: httpx.AsyncClient = world["viewer_client"]
    package = await _post(client, seed.slug, min_relevance=0.0)
    decision = next(i for i in package["items"] if i["id"] == str(seed.ids["decision"]))
    url = f"/api/v1/projects/{seed.slug}/context/requests/{package['request_id']}/feedback"

    bad = await client.post(url, json={"rating": 2, "item_flags": [{"citation": "S99", "flag": "wrong"}]})
    assert bad.status_code == 422
    assert "S99" in bad.json()["detail"]
    out_of_range = await client.post(url, json={"rating": 6})
    assert out_of_range.status_code == 422

    response = await client.post(
        url,
        json={
            "rating": 2,
            "comment": "La décision date un peu.",
            "item_flags": [{"citation": decision["citation"], "flag": "outdated"}],
        },
    )
    assert response.status_code == 200, response.text
    events = (
        await db_session.scalars(
            select(MemoryEvent).where(
                MemoryEvent.memory_item_id == seed.ids["decision"],
                MemoryEvent.event == MemoryEventType.obsoleted,
            )
        )
    ).all()
    assert len(events) == 1 and events[0].data.get("proposal") is True

    detail = (
        await admin_client.get(f"/api/v1/projects/{seed.slug}/context/requests/{package['request_id']}")
    ).json()
    assert detail["feedback"][0]["rating"] == 2
    history = (await admin_client.get(f"/api/v1/projects/{seed.slug}/context/requests")).json()
    assert history["items"][0]["rating"] == 2
    assert history["items"][0]["user"]["full_name"] == "Vera Viewer"


async def test_pinned_snapshot_flow_and_diff(
    world: dict[str, Any], admin_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    seed: Seed = world["seed"]
    client: httpx.AsyncClient = world["viewer_client"]
    slug = seed.slug

    v1 = await _post(client, slug, min_relevance=0.0, save_snapshot={"name": "spec-atlas"})
    assert v1["snapshot"]["name"] == "spec-atlas" and v1["snapshot"]["version"] == 1
    bad_name = await client.post(
        f"/api/v1/projects/{slug}/context", json={"task": TASK, "save_snapshot": {"name": "Spec Atlas !"}}
    )
    assert bad_name.status_code == 422

    # The decision is forgotten after v1: the pinned copy must be excluded with the reason.
    item = await db_session.get(MemoryItem, seed.ids["decision"])
    assert item is not None
    item.status = MemoryStatus.forgotten
    await db_session.commit()

    v2 = await _post(
        client,
        slug,
        task="Préparer le design de l'écran de connexion Atlas",
        min_relevance=0.0,
        base_snapshot={"name": "spec-atlas"},
        save_snapshot={"name": "spec-atlas"},
    )
    assert v2["snapshot"]["version"] == 2
    pinned = [i for i in v2["items"] if i["reason_code"] == "INCLUDED_PINNED"]
    assert pinned and all(i["reason_detail"] == "snapshot spec-atlas@v1" for i in pinned)
    forgotten = _by_code(v2, "EXCLUDED_FORGOTTEN")
    assert str(seed.ids["decision"]) in _ids(forgotten)

    groups = (await client.get(f"/api/v1/projects/{slug}/snapshots")).json()
    assert (
        groups[0]["name"] == "spec-atlas" and groups[0]["latest_version"] == 2 and groups[0]["versions"] == 2
    )

    versions = (await client.get(f"/api/v1/projects/{slug}/snapshots/spec-atlas")).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["parent_version"] == 1

    latest = await client.get(f"/api/v1/projects/{slug}/snapshots/spec-atlas/latest")
    assert latest.status_code == 200 and latest.json()["version"] == 2
    first = (await client.get(f"/api/v1/projects/{slug}/snapshots/spec-atlas/1")).json()
    key = f"memory:{seed.ids['decision_lineage']}"
    stored = next(i for i in first["items"] if i["key"] == key)
    assert stored["forgotten"] is True
    assert len(first["content_hash"]) == 64

    diff = await client.get(f"/api/v1/projects/{slug}/snapshots/spec-atlas/diff", params={"from": 1, "to": 2})
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["from"] == 1 and body["to"] == 2
    assert key in {i["key"] for i in body["removed"]}
    assert not ({i["key"] for i in body["added"]} & {i["key"] for i in body["unchanged"]})

    missing = await client.get(f"/api/v1/projects/{slug}/snapshots/spec-atlas/9")
    assert missing.status_code == 404
    unknown = await client.get(f"/api/v1/projects/{slug}/snapshots/inconnu")
    assert unknown.status_code == 404
    base_missing = await client.post(
        f"/api/v1/projects/{slug}/context", json={"task": TASK, "base_snapshot": {"name": "inconnu"}}
    )
    assert base_missing.status_code == 404
