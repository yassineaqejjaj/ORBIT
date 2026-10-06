"""MCP server: tool registration, authentication, and each tool over the real streamable HTTP transport.

Services owned by other modules (assembler, snapshots, memory lifecycle, short-term buffer, OpenSearch)
are replaced by small fakes so that the MCP layer itself (auth, argument handling, rights filtering,
serialisation, French errors) is tested deterministically. ``test_get_context_real_engine`` exercises
the real assembler and is marked xfail while that engine is not available.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import spotlight
from app.enums import (
    ActorType,
    CandidateType,
    ChunkStatus,
    DocumentStatus,
    Intent,
    MemoryKind,
    MemoryScope,
    PrincipalKind,
    ReasonCode,
    SourceKind,
)
from app.mcp_server import (
    SERVER_INSTRUCTIONS,
    TOOL_NAMES,
    build_mcp_server,
    extract_agent_key,
    parse_snapshot_ref,
)
from app.models import (
    AuditLog,
    Chunk,
    ContextFeedback,
    ContextRequest,
    ContextSnapshot,
    Document,
    MemoryItem,
    Source,
)
from app.schemas import ContextConfig, ContextItem, ContextPackage, ContextTimings, Scores
from app.search.opensearch import OSHit
from tests.conftest import UserInfo

EXPECTED_TOOLS = {
    "get_context",
    "get_snapshot",
    "search_sources",
    "propose_memory",
    "record_turn",
    "send_feedback",
}

# --- Pure units -----------------------------------------------------------------------------------------


async def test_tools_registered_exactly_as_contract() -> None:
    assert set(TOOL_NAMES) == EXPECTED_TOOLS
    tools = {tool.name: tool for tool in await build_mcp_server().list_tools()}
    assert set(tools) == EXPECTED_TOOLS
    required = {name: set(tool.input_schema.get("required", [])) for name, tool in tools.items()}
    assert required == {
        "get_context": {"task"},
        "get_snapshot": {"name"},
        "search_sources": {"query"},
        "propose_memory": {"kind", "title", "content"},
        "record_turn": {"session_id", "role", "content"},
        "send_feedback": {"request_id", "rating"},
    }
    props = set(tools["get_context"].input_schema["properties"])
    assert props == {
        "task",
        "intent",
        "token_budget",
        "scopes",
        "on_behalf_of",
        "session_id",
        "base_snapshot",
        "save_snapshot",
    }
    assert "ctx" not in json.dumps([t.input_schema for t in tools.values()])
    assert all(tool.description for tool in tools.values())


def test_extract_agent_key_variants() -> None:
    key = "orb_abcdefgh_" + "x" * 32
    assert extract_agent_key({"X-Orbit-Key": key}) == key
    assert extract_agent_key({"x-orbit-key": f"  {key} "}) == key
    assert extract_agent_key({"Authorization": f"Bearer {key}"}) == key
    assert extract_agent_key({"authorization": "Bearer eyJhbGciOi.jwt"}) is None
    assert extract_agent_key({"authorization": f"Basic {key}"}) is None
    assert extract_agent_key({}) is None
    assert extract_agent_key(None) is None


def test_parse_snapshot_ref() -> None:
    assert parse_snapshot_ref(None) is None
    assert parse_snapshot_ref("  ") is None
    ref = parse_snapshot_ref("spec-atlas")
    assert ref is not None and (ref.name, ref.version) == ("spec-atlas", None)
    ref = parse_snapshot_ref("spec-atlas@2")
    assert ref is not None and ref.version == 2
    ref = parse_snapshot_ref("spec-atlas@v3")
    assert ref is not None and ref.version == 3
    ref = parse_snapshot_ref("spec-atlas @ latest")
    assert ref is not None and ref.version is None
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="Référence de snapshot invalide"):
        parse_snapshot_ref("spec atlas@@")


def test_server_instructions_describe_orbit() -> None:
    assert "ORBIT" in SERVER_INSTRUCTIONS
    for tool in EXPECTED_TOOLS:
        assert tool in SERVER_INSTRUCTIONS


# --- Transport & authentication ---------------------------------------------------------------------------

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def test_mcp_requires_agent_key(client: httpx.AsyncClient) -> None:
    response = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthorized"
    assert "Clé d'agent requise" in body["detail"]
    assert response.headers["www-authenticate"].startswith("Bearer")

    bad = await client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "X-Orbit-Key": "orb_abcdefgh_" + "0" * 32}
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "Clé d'agent invalide"

    # A user session JWT is not an agent key.
    jwt_like = await client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": "Bearer abc"}
    )
    assert jwt_like.status_code == 401


@dataclass
class AgentSetup:
    slug: str
    project_id: uuid.UUID
    agent_id: uuid.UUID
    api_key: str
    member: UserInfo


@pytest.fixture
async def agent_setup(
    admin_client: httpx.AsyncClient,
    project: dict,  # type: ignore[type-arg]
    make_user,  # type: ignore[no-untyped-def]
) -> AgentSetup:
    slug = str(project["slug"])
    member: UserInfo = await make_user(clearance=2, name="Camille Martin")
    added = await admin_client.post(
        f"/api/v1/projects/{slug}/members", json={"email": member.email, "role": "owner"}
    )
    assert added.status_code == 201, added.text
    created = await admin_client.post(
        f"/api/v1/projects/{slug}/agents",
        json={"name": "Agent Produit", "kind": "product", "clearance": 2, "description": "Rédaction"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    return AgentSetup(
        slug=slug,
        project_id=uuid.UUID(str(project["id"])),
        agent_id=uuid.UUID(body["agent"]["id"]),
        api_key=body["api_key"],
        member=member,
    )


@asynccontextmanager
async def mcp_client(app: FastAPI, headers: dict[str, str]) -> AsyncIterator[Client]:
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver", headers=headers, timeout=30
    )
    async with http, Client(streamable_http_client("http://testserver/mcp", http_client=http)) as mcp:
        yield mcp


def payload(result: Any) -> Any:
    assert result.content, result
    return json.loads(result.content[0].text)


def error_text(result: Any) -> str:
    assert result.is_error, result
    return str(result.content[0].text)


async def test_initialize_and_list_tools_with_key(app: FastAPI, agent_setup: AgentSetup) -> None:
    for headers in ({"X-Orbit-Key": agent_setup.api_key}, {"Authorization": f"Bearer {agent_setup.api_key}"}):
        async with mcp_client(app, headers) as mcp:
            assert mcp.server_info is not None and mcp.server_info.name == "ORBIT"
            assert mcp.instructions and "ORBIT" in mcp.instructions
            tools = await mcp.list_tools()
            assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS


async def test_revoked_agent_is_rejected(
    app: FastAPI, admin_client: httpx.AsyncClient, agent_setup: AgentSetup, client: httpx.AsyncClient
) -> None:
    revoked = await admin_client.delete(f"/api/v1/projects/{agent_setup.slug}/agents/{agent_setup.agent_id}")
    assert revoked.status_code == 204
    response = await client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "X-Orbit-Key": agent_setup.api_key}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Clé d'agent révoquée"


# --- Tools ---------------------------------------------------------------------------------------------------


async def _context_request(
    session: AsyncSession, setup: AgentSetup, task: str = "Rédiger la spec"
) -> uuid.UUID:
    request = ContextRequest(
        project_id=setup.project_id,
        trace_id=uuid.uuid4().hex,
        agent_id=setup.agent_id,
        requested_by_type=PrincipalKind.agent,
        requested_by_id=setup.agent_id,
        task=task,
        intent=Intent.specification,
    )
    session.add(request)
    await session.commit()
    return request.id


async def test_send_feedback_persists_and_audits(
    app: FastAPI, agent_setup: AgentSetup, db_session: AsyncSession
) -> None:
    request_id = await _context_request(db_session, agent_setup)
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        invalid = await mcp.call_tool("send_feedback", {"request_id": "pas-un-uuid", "rating": 4})
        assert "request_id invalide" in error_text(invalid)
        unknown = await mcp.call_tool("send_feedback", {"request_id": str(uuid.uuid4()), "rating": 4})
        assert "Requête de contexte introuvable" in error_text(unknown)
        out_of_range = await mcp.call_tool("send_feedback", {"request_id": str(request_id), "rating": 9})
        assert out_of_range.is_error

        result = await mcp.call_tool(
            "send_feedback", {"request_id": str(request_id), "rating": 5, "comment": "  Très utile  "}
        )
        assert not result.is_error, result
        feedback_id = uuid.UUID(payload(result)["id"])

    feedback = await db_session.get(ContextFeedback, feedback_id)
    assert feedback is not None
    assert (feedback.rating, feedback.comment, feedback.actor_type) == (5, "Très utile", PrincipalKind.agent)
    assert feedback.actor_id == agent_setup.agent_id
    entry = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "context.feedback", AuditLog.target_id == str(request_id))
    )
    assert entry is not None and entry.actor_label == "Agent Produit" and entry.details["channel"] == "mcp"


async def test_send_feedback_cannot_target_another_project(
    app: FastAPI,
    agent_setup: AgentSetup,
    admin_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    other = await admin_client.post("/api/v1/projects", json={"name": "Projet voisin"})
    assert other.status_code == 201
    foreign = ContextRequest(
        project_id=uuid.UUID(other.json()["id"]),
        trace_id="t",
        requested_by_type=PrincipalKind.user,
        task="secret",
    )
    db_session.add(foreign)
    await db_session.commit()
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        result = await mcp.call_tool("send_feedback", {"request_id": str(foreign.id), "rating": 3})
        assert "Requête de contexte introuvable" in error_text(result)


def _fake_package(request: Any) -> ContextPackage:
    return ContextPackage(
        request_id=uuid.uuid4(),
        trace_id="0af7651916cd43dd8448eb211c80319c",
        task=request.task,
        intent=request.intent or Intent.specification,
        created_at=datetime.now(UTC),
        context="## Décisions en vigueur\n- L'application est une PWA [S1]\n\n## Sources\n[S1] CR atelier cadrage",
        items=[
            ContextItem(
                citation="S1",
                candidate_type=CandidateType.memory,
                id=str(uuid.uuid4()),
                memory_item_id=uuid.uuid4(),
                title="Décision : PWA",
                memory_kind=MemoryKind.decision,
                memory_scope=MemoryScope.project,
                excerpt="L'application sera une PWA",
                tokens=12,
                scores=Scores(final=0.82),
                classification=2,
                reason_code=ReasonCode.INCLUDED_RELEVANT,
                reason_detail="score 0,82 · décision validée · 35 j",
            )
        ],
        excluded=[],
        exclusion_summary={ReasonCode.EXCLUDED_SUPERSEDED: 2, ReasonCode.EXCLUDED_CLASSIFICATION: 1},
        tokens_used=312,
        token_budget=request.token_budget or 4000,
        candidates_count=18,
        timings=ContextTimings(total=120),
        config=ContextConfig(reranker="heuristic", embedding_model="hash"),
        warnings=["Le contexte contient des informations classifiées C2 (Confidentiel)."],
    )


async def test_get_context_builds_request_and_returns_citations(
    app: FastAPI, agent_setup: AgentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_assemble(session: AsyncSession, access: Any, request: Any) -> ContextPackage:
        captured.update(access=access, request=request)
        return _fake_package(request)

    monkeypatch.setattr("app.context.assembler.assemble_context", fake_assemble)
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        result = await mcp.call_tool(
            "get_context",
            {
                "task": "Rédiger la spécification du module de réservation",
                "intent": "specification",
                "token_budget": 3000,
                "scopes": ["project", "user"],
                "on_behalf_of": agent_setup.member.email.upper(),
                "session_id": "atlas-spec-redaction",
                "base_snapshot": "spec-atlas@v2",
                "save_snapshot": "design-atlas",
            },
        )
        assert not result.is_error, result
        data = payload(result)

    request = captured["request"]
    access = captured["access"]
    assert access.principal.kind == "agent" and access.project_id == agent_setup.project_id
    assert access.role.value == "editor"
    assert request.on_behalf_of == agent_setup.member.id
    assert request.explain is False
    assert request.base_snapshot.name == "spec-atlas" and request.base_snapshot.version == 2
    assert request.save_snapshot.name == "design-atlas"
    assert request.token_budget == 3000 and [s.value for s in request.scopes] == ["project", "user"]

    assert set(data) >= {"context", "citations", "exclusion_summary", "request_id", "snapshot"}
    assert data["citations"][0]["citation"] == "S1"
    assert data["citations"][0]["type"] == "memory"
    assert data["exclusion_summary"] == {"EXCLUDED_SUPERSEDED": 2, "EXCLUDED_CLASSIFICATION": 1}
    assert data["warnings"] and "C2" in data["warnings"][0]
    assert "excluded" not in data  # agents only receive counters


async def test_get_context_rejects_non_member_and_bad_arguments(
    app: FastAPI,
    agent_setup: AgentSetup,
    make_user,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_assemble(session: AsyncSession, access: Any, request: Any) -> ContextPackage:
        return _fake_package(request)

    monkeypatch.setattr("app.context.assembler.assemble_context", fake_assemble)
    outsider: UserInfo = await make_user()
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        result = await mcp.call_tool("get_context", {"task": "x", "on_behalf_of": outsider.email})
        assert "utilisateur introuvable parmi les membres" in error_text(result)
        result = await mcp.call_tool("get_context", {"task": "x", "on_behalf_of": str(uuid.uuid4())})
        assert result.is_error
        result = await mcp.call_tool("get_context", {"task": "x", "base_snapshot": "spec atlas!"})
        assert "Référence de snapshot invalide" in error_text(result)
        result = await mcp.call_tool("get_context", {"task": "x", "save_snapshot": "nom invalide !"})
        assert "Données invalides" in error_text(result)


async def test_get_context_real_engine(app: FastAPI, agent_setup: AgentSetup) -> None:
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        result = await mcp.call_tool("get_context", {"task": "Quelles décisions sont en vigueur ?"})
    if result.is_error:
        message = error_text(result)
        if "non implémenté" in message or "non disponible" in message or "pas encore" in message:
            pytest.xfail(f"moteur de contexte indisponible : {message}")
        pytest.fail(message)
    data = payload(result)
    assert data["request_id"] and isinstance(data["citations"], list)


async def test_record_turn_uses_project_ttl(
    app: FastAPI, agent_setup: AgentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    expires = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    async def fake_append(project_id: uuid.UUID, session_id: str, role: Any, content: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        calls.append(
            {"project_id": project_id, "session_id": session_id, "role": role, "content": content, **kwargs}
        )
        return 4, expires

    monkeypatch.setattr("app.memory.short_term.append_turn", fake_append)
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        bad = await mcp.call_tool(
            "record_turn", {"session_id": "espace interdit", "role": "agent", "content": "x"}
        )
        assert "session_id invalide" in error_text(bad)
        result = await mcp.call_tool(
            "record_turn",
            {"session_id": "atlas-spec-redaction", "role": "agent", "content": "Plan de la spec"},
        )
        assert not result.is_error, result
        assert payload(result) == {
            "session_id": "atlas-spec-redaction",
            "turns": 4,
            "expires_at": expires.isoformat(),
        }
    assert calls[0]["ttl_hours"] == 72 and calls[0]["agent_id"] == agent_setup.agent_id
    assert calls[0]["role"].value == "agent" and calls[0]["project_id"] == agent_setup.project_id


async def _documents(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    source = Source(project_id=project_id, name="Spécifications", kind=SourceKind.document)
    session.add(source)
    await session.flush()
    public = Document(
        project_id=project_id,
        source_id=source.id,
        title="Spécification fonctionnelle Atlas",
        classification=1,
        status=DocumentStatus.indexed,
    )
    secret = Document(
        project_id=project_id,
        source_id=source.id,
        title="Budget et négociation contrat Atlas",
        classification=3,
        acl_principals=["role:owner"],
        status=DocumentStatus.indexed,
    )
    owners_only = Document(
        project_id=project_id,
        source_id=source.id,
        title="Note RH",
        classification=1,
        acl_principals=["role:owner"],
        status=DocumentStatus.indexed,
    )
    session.add_all([public, secret, owners_only])
    await session.flush()

    def chunk(doc: Document, text: str, **kwargs: Any) -> Chunk:
        return Chunk(
            project_id=project_id,
            document_id=doc.id,
            version=1,
            ordinal=0,
            text=text,
            text_redacted=text.replace("camille.martin@nordalis.example", "[EMAIL]"),
            classification=doc.classification,
            acl_principals=list(doc.acl_principals),
            section="Périmètre",
            **kwargs,
        )

    visible = chunk(public, "Le pilote couvre 650 postes. Contact : camille.martin@nordalis.example")
    superseded = chunk(public, "Ancienne version : 800 postes", status=ChunkStatus.superseded)
    hidden = chunk(secret, "Plafond budgétaire 480 k€")
    owner_chunk = chunk(owners_only, "Organisation des équipes")
    session.add_all([visible, superseded, hidden, owner_chunk])
    await session.commit()
    return {
        "source": source,
        "public": public,
        "secret": secret,
        "visible": visible,
        "superseded": superseded,
        "hidden": hidden,
        "owner_chunk": owner_chunk,
    }


async def test_search_sources_filters_rights_and_redacts(
    app: FastAPI, agent_setup: AgentSetup, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = await _documents(db_session, agent_setup.project_id)
    seen_filters: list[Any] = []
    stale_index = [
        OSHit(str(rows["hidden"].id), 14.0),
        OSHit(str(rows["visible"].id), 11.0),
        OSHit(str(rows["superseded"].id), 9.0),
        OSHit(str(rows["owner_chunk"].id), 5.0),
        OSHit("not-a-uuid", 1.0),
    ]

    async def fake_bm25(kind: str, query: str, **kwargs: Any) -> list[OSHit]:
        seen_filters.append(kwargs["filters"])
        assert kind == "chunks" and kwargs["project_id"] == str(agent_setup.project_id)
        return stale_index

    async def fake_knn(kind: str, vector: Any, **kwargs: Any) -> list[OSHit]:
        return [OSHit(str(rows["visible"].id), 0.93)]

    class FakeEmbedder:
        model_name = "hash"
        dim = 4

        async def embed_query(self, text: str) -> list[float]:
            return [0.5, 0.5, 0.5, 0.5]

    async def fake_aget_embedder() -> FakeEmbedder:
        return FakeEmbedder()

    monkeypatch.setattr("app.search.opensearch.bm25_search", fake_bm25)
    monkeypatch.setattr("app.search.opensearch.knn_search", fake_knn)
    monkeypatch.setattr("app.search.embeddings.aget_embedder", fake_aget_embedder)

    async with mcp_client(app, {"Authorization": f"Bearer {agent_setup.api_key}"}) as mcp:
        result = await mcp.call_tool("search_sources", {"query": "nombre de postes du pilote", "limit": 5})
        assert not result.is_error, result
        hits = [json.loads(block.text) for block in result.content]  # one content block per SearchHit

    assert [hit["chunk_id"] for hit in hits] == [str(rows["visible"].id)]
    hit = hits[0]
    assert hit["text"] == spotlight.wrap("Le pilote couvre 650 postes. Contact : [EMAIL]")  # §A2
    assert hit["document_title"] == "Spécification fonctionnelle Atlas"
    assert hit["source_kind"] == "document" and hit["bm25"] == 11.0 and hit["dense"] == 0.93
    filters = json.dumps(seen_filters[0])
    assert '"acl_principals": ["project:*"]' in filters
    assert '"lte": 2' in filters and '"status": "active"' in filters


async def test_search_sources_unavailable_index(
    app: FastAPI, agent_setup: AgentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def not_ready(*args: Any, **kwargs: Any) -> list[OSHit]:
        raise NotImplementedError

    monkeypatch.setattr("app.search.opensearch.bm25_search", not_ready)
    monkeypatch.setattr("app.search.opensearch.knn_search", not_ready)
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        result = await mcp.call_tool("search_sources", {"query": "postes"})
        assert "Recherche indisponible" in error_text(result)


async def test_propose_memory_forces_proposed_status(
    app: FastAPI, agent_setup: AgentSetup, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = await _documents(db_session, agent_setup.project_id)
    calls: list[dict[str, Any]] = []

    async def fake_create_item(
        session: AsyncSession, *, project_id: Any, data: Any, actor: Any, force_status: Any = None
    ) -> MemoryItem:
        calls.append({"project_id": project_id, "data": data, "actor": actor, "force_status": force_status})
        item = MemoryItem(
            project_id=project_id,
            scope=data.scope,
            kind=data.kind,
            status=force_status or "validated",
            title=data.title,
            content=data.content,
            classification=data.classification if data.classification is not None else 1,
            created_by_type=ActorType.agent,
            created_by_id=actor.id,
        )
        session.add(item)
        await session.flush()
        return item

    monkeypatch.setattr("app.memory.lifecycle.create_item", fake_create_item)
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        denied_scope = await mcp.call_tool(
            "propose_memory", {"kind": "preference", "title": "t", "content": "c", "scope": "user"}
        )
        assert "Portée non autorisée" in error_text(denied_scope)
        hidden_doc = await mcp.call_tool(
            "propose_memory",
            {
                "kind": "fact",
                "title": "Budget",
                "content": "Le plafond est connu",
                "provenance_document_ids": [str(rows["secret"].id)],
            },
        )
        assert f"Document introuvable : {rows['secret'].id}" in error_text(hidden_doc)

        result = await mcp.call_tool(
            "propose_memory",
            {
                "kind": "requirement",
                "title": "Besoin : réserver depuis Teams",
                "content": "En tant que collaborateur, je veux réserver un poste depuis Microsoft Teams.",
                "provenance_document_ids": [str(rows["public"].id)],
            },
        )
        assert not result.is_error, result
        item = payload(result)

    assert item["status"] == "proposed"
    assert item["created_by_label"] == "Agent Produit" and item["provenance_count"] == 1
    call = calls[-1]
    assert call["force_status"] == "proposed" and call["project_id"] == agent_setup.project_id
    assert call["data"].provenance[0].document_id == rows["public"].id
    assert call["data"].provenance[0].source_label == "Spécification fonctionnelle Atlas"
    assert call["actor"].kind == "agent"
    stored = await db_session.get(MemoryItem, uuid.UUID(item["id"]))
    assert stored is not None and stored.title == "Besoin : réserver depuis Teams"


async def test_get_snapshot_hides_restricted_items(
    app: FastAPI, agent_setup: AgentSetup, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = await _documents(db_session, agent_setup.project_id)
    items = [
        {
            "key": f"chunk:{rows['visible'].id}",
            "citation": "S1",
            "candidate_type": "chunk",
            "id": str(rows["visible"].id),
            "title": "Spécification fonctionnelle Atlas",
            "excerpt": "Le pilote couvre 650 postes.",
            "source_kind": "document",
            "version": 2,
            "forgotten": False,
        },
        {
            "key": f"chunk:{rows['hidden'].id}",
            "citation": "S2",
            "candidate_type": "chunk",
            "id": str(rows["hidden"].id),
            "title": "Budget et négociation contrat Atlas",
            "excerpt": "Plafond budgétaire 480 k€",
            "source_kind": "document",
            "forgotten": False,
        },
    ]
    v1 = ContextSnapshot(
        project_id=agent_setup.project_id,
        name="spec-atlas",
        version=1,
        task="Rédiger la spécification",
        intent=Intent.specification,
        content="[S1] 650 postes\n[S2] Plafond budgétaire 480 k€",
        items=items,
        content_hash="h1",
        token_count=40,
        created_by_type=ActorType.agent,
        created_by_id=agent_setup.agent_id,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(v1)
    await db_session.flush()
    v2 = ContextSnapshot(
        project_id=agent_setup.project_id,
        name="spec-atlas",
        version=2,
        parent_id=v1.id,
        task="Mettre à jour la spécification",
        intent=Intent.specification,
        content="[S1] 650 postes",
        items=items[:1],
        content_hash="h2",
        token_count=20,
        created_by_type=ActorType.agent,
        created_by_id=agent_setup.agent_id,
    )
    db_session.add(v2)
    await db_session.commit()

    async def fake_get_snapshot(session: AsyncSession, project_id: uuid.UUID, name: str, version: Any = None):  # type: ignore[no-untyped-def]
        stmt = select(ContextSnapshot).where(
            ContextSnapshot.project_id == project_id, ContextSnapshot.name == name
        )
        if isinstance(version, int):
            stmt = stmt.where(ContextSnapshot.version == version)
        return await session.scalar(stmt.order_by(ContextSnapshot.version.desc()).limit(1))

    monkeypatch.setattr("app.context.snapshots.get_snapshot", fake_get_snapshot)
    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        latest = payload(await mcp.call_tool("get_snapshot", {"name": "spec-atlas"}))
        first = payload(await mcp.call_tool("get_snapshot", {"name": "spec-atlas", "version": 1}))
        missing = await mcp.call_tool("get_snapshot", {"name": "design-atlas"})

    assert latest["version"] == 2 and latest["parent_version"] == 1 and latest["restricted_items"] == 0
    assert latest["content"] == spotlight.wrap("[S1] 650 postes") and latest["created_by_label"] == "Agent Produit"
    assert first["restricted_items"] == 1 and first["items_count"] == 1
    assert [i["citation"] for i in first["items"]] == ["S1"]
    assert "480" not in first["content"] and "Budget" not in json.dumps(first)
    assert "Snapshot « design-atlas » introuvable" in error_text(missing)
