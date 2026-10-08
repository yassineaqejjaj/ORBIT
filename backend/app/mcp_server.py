"""ORBIT MCP server (docs/API.md « MCP ») — streamable HTTP on ``/mcp``.

Contract with ``app.main``:

* ``build_mcp_app()`` returns a Starlette application built with ``streamable_http_path="/mcp"``;
  ``app.main`` forwards ``/mcp`` untouched and enters its lifespan (streamable HTTP session manager).
* The transport is **stateless** with JSON responses: any replica can serve any call, and there is
  no server-side MCP session to leak between agents.

Authentication — an agent API key is mandatory (``Authorization: Bearer orb_…`` or ``X-Orbit-Key``):

* :class:`AgentKeyGate` rejects unauthenticated HTTP requests with ``401`` before the MCP handshake;
* every tool call re-validates the key from the request headers (``app.deps.authenticate_agent_key``)
  and acts as ``Principal.for_agent(agent)`` with the ``editor`` role on **the agent's own project**,
  exactly like the REST endpoints marked *(agent)*.

Tools reuse the same services as REST: ``app.context.assembler.assemble_context``,
``app.context.snapshots.get_snapshot``, ``app.search.hybrid.hybrid_search`` (with the agent's ACL /
clearance pre-filters, every hit re-checked against Postgres), ``app.memory.lifecycle.create_item``,
``app.memory.short_term.append_turn`` and ``app.context.persistence.record_feedback``. Agents only
ever receive ``text_redacted`` (PII masked) and exclusion **counters** (non-leak principle, §3).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.context import spotlight
from app.db import get_sessionmaker
from app.deps import Principal, ProjectAccess, authenticate_agent_key
from app.enums import (
    ActorType,
    CandidateType,
    ChunkStatus,
    DocumentStatus,
    Intent,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    PrincipalKind,
    Role,
    TurnRole,
)
from app.errors import ApiError, format_validation_errors
from app.governance.acl import PROJECT_ALL, acl_terms_filter
from app.models import (
    Chunk,
    ContextRequest,
    ContextSnapshot,
    Document,
    MemoryItem,
    Project,
    Source,
    User,
)
from app.schemas import (
    BaseSnapshotRef,
    ContextPackage,
    ContextRequestIn,
    FeedbackIn,
    MemoryIn,
    ProvenanceIn,
    SaveSnapshotRef,
    SearchHit,
    Snapshot,
    SnapshotItem,
)
from app.schemas import MemoryItem as MemoryItemOut
from app.security import API_KEY_HEADER, looks_like_api_key
from app.services import audit
from app.services import projects as project_service
from app.services.audit import AuditAction
from app.services.metrics import Visibility, actor_labels

logger = logging.getLogger("orbit.mcp")

MCP_PATH = "/mcp"
SERVER_NAME = "ORBIT"
SERVER_TITLE = "ORBIT — contexte et mémoire gouvernés pour agents IA"

SERVER_INSTRUCTIONS = """\
ORBIT est la plateforme de contexte et de mémoire de votre organisation. Elle fournit à l'agent les
informations utiles à sa tâche — décisions en vigueur, besoins, contraintes, extraits de sources — en
tenant compte de leur pertinence, de leur fraîcheur, de leur provenance et des droits d'accès.
Chaque contenu servi est cité ([S1], [S2]…) et chaque exclusion est expliquée et auditée.

Vous agissez au nom d'un agent rattaché à un seul projet (celui de votre clé API).

Bonnes pratiques :
1. Au début d'une tâche, appelez `get_context` avec la tâche en langage naturel. Renseignez
   `on_behalf_of` (UUID ou e-mail du membre pour lequel vous travaillez) : vous héritez alors de ses
   droits, sinon seuls les contenus ouverts à tout le projet sont servis.
2. Appuyez vos réponses sur le champ `context` et citez les sources avec leurs repères [S1]…
   Si `warnings` n'est pas vide (contenus C2 Confidentiel / C3 Secret), relayez l'avertissement.
3. Pour partir d'un contexte commun (par ex. celui de l'agent produit), passez `base_snapshot`
   (« spec-atlas » ou « spec-atlas@2 ») ; `save_snapshot` enregistre votre contexte comme nouvelle
   version partagée. `get_snapshot` relit une version existante.
4. `search_sources` sert aux vérifications ponctuelles dans les documents indexés.
5. `record_turn` conserve les échanges importants d'une session de travail (mémoire court terme).
6. `propose_memory` propose une décision, un besoin, une contrainte, un risque ou un fait : il reste
   « proposé » jusqu'à validation par un humain.
7. Terminez par `send_feedback` (note 1–5) avec le `request_id` reçu pour améliorer la sélection.
8. Contexte à la demande : `get_context` avec `mode="progressive"` renvoie un résumé et un index
   (identifiants) ; dépliez un élément avec `expand_source`, `get_decision` ou `get_memory_item`, et
   lancez `search_more` si `sufficiency.verdict` vaut « partial » ou « insufficient » (sous-sujets
   manquants dans `sufficiency.missing_subtopics`). Si le contexte reste insuffisant, dites que vous
   ne savez pas plutôt que de deviner. `cache_hints=true` renvoie les blocs `cache_control`.

Les données personnelles sont masquées ([EMAIL], [TÉLÉPHONE]…) et les contenus hors habilitation ne
sont jamais transmis, pas même leur titre.
"""

MISSING_KEY_MESSAGE = (
    "Clé d'agent requise : envoyez « Authorization: Bearer orb_… » ou l'en-tête « X-Orbit-Key »"
)
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:\-]{1,200}$")
SNAPSHOT_REF_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._\-]*)\s*(?:@\s*(?:v?(?P<version>\d+)|(?P<latest>latest)))?\s*$"
)
#: Memory scopes an agent may propose through MCP (short-term memory goes through ``record_turn``).
PROPOSABLE_SCOPES: frozenset[MemoryScope] = frozenset({MemoryScope.project, MemoryScope.long_term})
FORGOTTEN_EXCERPT = "[oublié]"


# --- Authentication -----------------------------------------------------------------------------------


def extract_agent_key(headers: Mapping[str, str] | None) -> str | None:
    """Agent key from ``X-Orbit-Key`` or ``Authorization: Bearer orb_…`` (case-insensitive header names)."""
    if not headers:
        return None
    lowered = {str(name).lower(): str(value) for name, value in headers.items()}
    explicit = lowered.get(API_KEY_HEADER.lower(), "").strip()
    if explicit:
        return explicit
    scheme, _, token = lowered.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() == "bearer" and looks_like_api_key(token):
        return token
    return None


class AgentKeyGate:
    """ASGI middleware: reject HTTP requests without a valid, active agent key (401 JSON, French)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        key = extract_agent_key(Headers(scope=scope))
        if key is None:
            await _reject(scope, receive, send, 401, MISSING_KEY_MESSAGE, "unauthorized")
            return
        try:
            async with get_sessionmaker()() as session:
                await authenticate_agent_key(session, key, touch=True)
        except ApiError as exc:
            await _reject(scope, receive, send, exc.status_code, str(exc.detail), exc.code)
            return
        except Exception:
            logger.exception("MCP authentication backend unavailable")
            await _reject(
                scope,
                receive,
                send,
                503,
                "Service d'authentification indisponible, réessayez plus tard",
                "unavailable",
            )
            return
        await self.app(scope, receive, send)


async def _reject(scope: Scope, receive: Receive, send: Send, status: int, detail: str, code: str) -> None:
    headers = {"WWW-Authenticate": 'Bearer realm="orbit-mcp"'} if status == 401 else None
    response = JSONResponse({"detail": detail, "code": code}, status_code=status, headers=headers)
    await response(scope, receive, send)


@dataclass(slots=True)
class AgentScope:
    """Database session + resolved project access of the calling agent (one per tool call)."""

    session: AsyncSession
    access: ProjectAccess

    @property
    def project(self) -> Project:
        return self.access.project

    @property
    def principal(self) -> Principal:
        return self.access.principal

    @property
    def visibility(self) -> Visibility:
        """An agent without ``on_behalf_of`` only reads ``project:*`` content up to its clearance."""
        return Visibility(frozenset({PROJECT_ALL}), int(self.principal.clearance))


def to_tool_error(exc: BaseException) -> ToolError:
    """Translate service exceptions into a French message returned to the agent (``is_error``)."""
    if isinstance(exc, ToolError):
        return exc
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Requête refusée"
        return ToolError(detail)
    if isinstance(exc, ValidationError):
        message, _items = format_validation_errors([dict(e) for e in exc.errors()])
        return ToolError(message)
    if isinstance(exc, NotImplementedError):
        return ToolError(str(exc) or "Fonctionnalité non disponible sur cette instance ORBIT")
    logger.exception("Unexpected error in MCP tool", exc_info=exc)
    return ToolError("Erreur interne ORBIT — l'incident a été journalisé")


def _headers(ctx: Context) -> Mapping[str, str] | None:
    try:
        return ctx.headers
    except ValueError:  # outside of a request (no transport)
        return None


@asynccontextmanager
async def agent_scope(ctx: Context) -> AsyncIterator[AgentScope]:
    """Authenticate the agent of the current MCP request and open a transaction scope.

    Every exception raised by the tool body is translated into a :class:`ToolError` (French message).
    """
    key = extract_agent_key(_headers(ctx))
    if key is None:
        raise ToolError(MISSING_KEY_MESSAGE)
    async with get_sessionmaker()() as session:
        try:
            agent = await authenticate_agent_key(session, key, touch=False)
            project = await session.get(Project, agent.project_id)
            if project is None:
                raise ToolError("Projet de l'agent introuvable")
            access = ProjectAccess(project=project, principal=Principal.for_agent(agent), role=Role.editor)
            yield AgentScope(session=session, access=access)
        except ToolError:
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            raise to_tool_error(exc) from exc


# --- Argument helpers ---------------------------------------------------------------------------------


def parse_snapshot_ref(value: str | None) -> BaseSnapshotRef | None:
    """``"spec-atlas"`` / ``"spec-atlas@2"`` / ``"spec-atlas@v2"`` / ``"spec-atlas@latest"``."""
    if value is None or not value.strip():
        return None
    match = SNAPSHOT_REF_PATTERN.match(value)
    if match is None:
        raise ToolError(f"Référence de snapshot invalide « {value} » (attendu : nom, nom@3 ou nom@latest)")
    version = match.group("version")
    return BaseSnapshotRef(name=match.group("name"), version=int(version) if version else None)


async def resolve_member(scope: AgentScope, value: str) -> uuid.UUID:
    """``on_behalf_of`` given as a UUID or an e-mail, restricted to members of the agent's project."""
    candidate = value.strip()
    user: User | None = None
    if "@" in candidate:
        user = await scope.session.scalar(select(User).where(func.lower(User.email) == candidate.lower()))
    else:
        try:
            user = await scope.session.get(User, uuid.UUID(candidate))
        except ValueError:
            user = None
    if (
        user is None
        or await project_service.get_member_role(scope.session, scope.project.id, user.id) is None
    ):
        raise ToolError("on_behalf_of : utilisateur introuvable parmi les membres du projet")
    return user.id


def _uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value).strip())
    except ValueError as exc:
        raise ToolError(f"{label} invalide : identifiant UUID attendu") from exc


def context_result(package: ContextPackage) -> dict[str, Any]:
    """MCP view of a context package: text, citations, counters (no excluded details)."""
    data = package.model_dump(mode="json")
    citations = [
        {
            "citation": item["citation"],
            "title": item["title"],
            "type": item["candidate_type"],
            "source_kind": item.get("source_kind"),
            "memory_kind": item.get("memory_kind"),
            "memory_scope": item.get("memory_scope"),
            "uri": item.get("uri"),
            "version": item.get("version"),
            "date": item.get("date"),
            "classification": item["classification"],
            "pii_redacted": item.get("pii_redacted", False),
        }
        for item in data["items"]
    ]
    return {
        "request_id": data["request_id"],
        "trace_id": data["trace_id"],
        "intent": data["intent"],
        "context": data["context"],
        "citations": citations,
        "exclusion_summary": data["exclusion_summary"],
        "snapshot": data["snapshot"],
        "tokens_used": data["tokens_used"],
        "token_budget": data["token_budget"],
        "warnings": data["warnings"],
        "sufficiency": data.get("sufficiency"),
        "cache_prefix_hash": data.get("cache_prefix_hash"),
        "cache_prefix_tokens": data.get("cache_prefix_tokens", 0),
        **({"cache_hints": data["cache_hints"]} if data.get("cache_hints") else {}),
        **({"mode": "progressive", "index": data["index"]} if data.get("mode") == "progressive" else {}),
        **_untrusted_notice(),
    }


def _untrusted_notice() -> dict[str, str]:
    """§A2: every MCP result carrying source content says it is untrusted data."""
    return {"untrusted_content_notice": spotlight.MCP_NOTICE} if spotlight.enabled() else {}


# --- Tools --------------------------------------------------------------------------------------------

TaskArg = Annotated[
    str, Field(min_length=1, max_length=8000, description="Tâche à accomplir, en langage naturel")
]
OnBehalfArg = Annotated[
    str | None,
    Field(description="UUID ou e-mail du membre du projet pour le compte duquel l'agent travaille"),
]
SessionIdArg = Annotated[
    str | None,
    Field(max_length=200, description="Identifiant de session de travail (réinjecte ses tours récents)"),
]


async def get_context(
    task: TaskArg,
    ctx: Context,
    intent: Annotated[Intent | None, Field(description="Intention ; déduite de la tâche si omise")] = None,
    token_budget: Annotated[
        int | None, Field(ge=500, le=32000, description="Budget de tokens (défaut : paramètre du projet)")
    ] = None,
    scopes: Annotated[
        list[MemoryScope] | None, Field(description="Portées mémoire (défaut : toutes)")
    ] = None,
    on_behalf_of: OnBehalfArg = None,
    session_id: SessionIdArg = None,
    base_snapshot: Annotated[
        str | None, Field(description="Snapshot de départ : « nom », « nom@3 » ou « nom@latest »")
    ] = None,
    save_snapshot: Annotated[
        str | None, Field(description="Enregistre le contexte comme nouvelle version de ce snapshot")
    ] = None,
    cache_hints: Annotated[
        bool, Field(description="Blocs de texte avec points d'arrêt cache_control (format Anthropic)")
    ] = False,
    mode: Annotated[
        Literal["full", "progressive"],
        Field(description="progressive : résumé + index avec identifiants, détail via expand_source…"),
    ] = "full",
) -> dict[str, Any]:
    """Assemble a governed context package for the task (same engine as ``POST /context``)."""
    from app.context.assembler import assemble_context

    async with agent_scope(ctx) as scope:
        behalf = await resolve_member(scope, on_behalf_of) if on_behalf_of else None
        body = ContextRequestIn(
            task=task,
            intent=intent,
            token_budget=token_budget,
            scopes=scopes,
            on_behalf_of=behalf,
            session_id=session_id,
            base_snapshot=parse_snapshot_ref(base_snapshot),
            save_snapshot=SaveSnapshotRef(name=save_snapshot.strip()) if save_snapshot else None,
            explain=False,
            cache_hints=cache_hints,
            mode=mode,
        )
        package = await assemble_context(scope.session, scope.access, body)
        return context_result(package)


async def get_snapshot(
    name: Annotated[str, Field(min_length=1, max_length=120, description="Nom du snapshot, ex. spec-atlas")],
    ctx: Context,
    version: Annotated[
        int | Literal["latest"] | None, Field(description="Numéro de version ou « latest » (défaut)")
    ] = None,
) -> dict[str, Any]:
    """Read one version of a shared context snapshot, filtered by the agent's rights."""
    from app.context import snapshots as snapshot_service

    if isinstance(version, int) and version < 1:
        raise ToolError("version : entier supérieur ou égal à 1 attendu")
    async with agent_scope(ctx) as scope:
        snapshot = await snapshot_service.get_snapshot(
            scope.session, scope.project.id, name.strip(), version if version is not None else "latest"
        )
        if snapshot is None:
            suffix = f" en version {version}" if isinstance(version, int) else ""
            raise ToolError(f"Snapshot « {name} »{suffix} introuvable")
        return await snapshot_view(scope.session, snapshot, scope.visibility)


async def search_sources(
    query: Annotated[str, Field(min_length=1, max_length=1000, description="Recherche en langage naturel")],
    ctx: Context,
    limit: Annotated[int, Field(ge=1, le=50, description="Nombre maximal de résultats")] = 10,
) -> list[dict[str, Any]]:
    """Hybrid search (BM25 + k-NN) over the project's indexed chunks, restricted to the agent's rights."""
    async with agent_scope(ctx) as scope:
        hits = await hybrid_chunk_search(scope, query.strip(), limit)
        return [{**hit.model_dump(mode="json"), **_untrusted_notice()} for hit in hits]


async def propose_memory(
    kind: Annotated[MemoryKind, Field(description="decision, requirement, constraint, risk, fact…")],
    title: Annotated[str, Field(min_length=1, max_length=300, description="Titre court et autoportant")],
    content: Annotated[str, Field(min_length=1, max_length=20000, description="Énoncé complet")],
    ctx: Context,
    scope: Annotated[
        MemoryScope, Field(description="« project » (défaut) ou « long_term »")
    ] = MemoryScope.project,
    provenance_document_ids: Annotated[
        list[str] | None,
        Field(max_length=20, description="Documents sources (UUID) justifiant la proposition"),
    ] = None,
) -> dict[str, Any]:
    """Propose a memory item (always ``proposed`` until a human validates it)."""
    from app.memory import lifecycle

    if scope not in PROPOSABLE_SCOPES:
        raise ToolError(
            "Portée non autorisée pour une proposition d'agent : utilisez « project » ou « long_term » "
            "(la mémoire court terme passe par record_turn)"
        )
    async with agent_scope(ctx) as agent:
        documents = await _provenance_documents(agent, provenance_document_ids or [])
        data = MemoryIn(
            scope=scope,
            kind=kind,
            title=title,
            content=content,
            classification=max((d.classification for d in documents), default=None),
            provenance=[ProvenanceIn(document_id=d.id, source_label=d.title[:300]) for d in documents]
            or None,
            status="proposed",
        )
        item = await lifecycle.create_item(
            agent.session,
            project_id=agent.project.id,
            data=data,
            actor=agent.principal,
            force_status=MemoryStatus.proposed.value,
        )
        await agent.session.commit()
        view = MemoryItemOut.model_validate(item).model_copy(
            update={"created_by_label": agent.principal.label, "provenance_count": len(documents)}
        )
        return view.model_dump(mode="json")


async def record_turn(
    session_id: Annotated[str, Field(min_length=1, max_length=200, description="Identifiant de session")],
    role: Annotated[TurnRole, Field(description="user, agent ou tool")],
    content: Annotated[str, Field(min_length=1, max_length=50000, description="Contenu du tour")],
    ctx: Context,
) -> dict[str, Any]:
    """Append a turn to the short-term memory of a work session (TTL of the project)."""
    from app.memory import short_term

    session_id = session_id.strip()
    if not SESSION_ID_PATTERN.match(session_id):
        raise ToolError("session_id invalide : lettres, chiffres, « . », « _ », « : » et « - » uniquement")
    async with agent_scope(ctx) as scope:
        ttl_hours = project_service.settings_model(scope.project).short_term_ttl_hours
        turns, expires_at = await short_term.append_turn(
            scope.project.id,
            session_id,
            role,
            content,
            ttl_hours=ttl_hours,
            agent_id=scope.principal.agent_id,
        )
        return {"session_id": session_id, "turns": int(turns), "expires_at": expires_at.isoformat()}


async def send_feedback(
    request_id: Annotated[str, Field(description="request_id renvoyé par get_context")],
    rating: Annotated[int, Field(ge=1, le=5, description="Note de 1 (inutile) à 5 (parfait)")],
    ctx: Context,
    comment: Annotated[str | None, Field(max_length=4000, description="Commentaire libre")] = None,
) -> dict[str, Any]:
    """Rate a context previously served in this project (same persistence as the REST endpoint)."""
    from app.context.persistence import record_feedback

    target = _uuid(request_id, "request_id")
    async with agent_scope(ctx) as scope:
        request = await scope.session.get(ContextRequest, target)
        if request is None or request.project_id != scope.project.id:
            raise ToolError("Requête de contexte introuvable")
        cleaned = comment.strip() if comment and comment.strip() else None
        feedback = await record_feedback(
            scope.session,
            request,
            FeedbackIn(rating=rating, comment=cleaned),
            actor=scope.principal,
            actor_kind=PrincipalKind.agent,
        )
        await audit.record(
            scope.session,
            scope.project.id,
            scope.principal,
            AuditAction.context_feedback,
            "context_request",
            request.id,
            summary=f"Évaluation {rating}/5 du contexte « {request.task[:80]} »",
            details={"rating": rating, "channel": "mcp", "feedback_id": feedback.id},
        )
        await scope.session.commit()
        return {"id": str(feedback.id)}


# --- Tool internals -----------------------------------------------------------------------------------


IdArg = Annotated[str, Field(min_length=1, max_length=100, description="Identifiant renvoyé par l'index")]


@asynccontextmanager
async def _governed(ctx: Context, on_behalf_of: str | None) -> AsyncIterator[tuple[AgentScope, Any]]:
    """§C2: agent scope + the context engine's identity/governance (``app.context.expand``)."""
    from app.context import expand

    async with agent_scope(ctx) as scope:
        behalf = await resolve_member(scope, on_behalf_of) if on_behalf_of else None
        gov = await expand.governed(scope.session, scope.access, behalf)
        try:
            yield scope, gov
        except expand.LookupDenied as exc:
            await scope.session.commit()  # the refusal is audited
            raise ToolError(exc.message) from exc
        await scope.session.commit()


async def expand_source(
    source_id: IdArg,
    ctx: Context,
    max_tokens: Annotated[int, Field(ge=100, le=16000, description="Taille maximale du texte")] = 2000,
    on_behalf_of: OnBehalfArg = None,
) -> dict[str, Any]:
    """Full text of a source extract (chunk id) or of a document (document id), governed and audited."""
    from app.context import expand

    async with _governed(ctx, on_behalf_of) as (scope, gov):
        result = await expand.expand_source(scope.session, gov, source_id, max_tokens=max_tokens)
        return {**result, **_untrusted_notice()}


async def get_decision(decision_id: IdArg, ctx: Context, on_behalf_of: OnBehalfArg = None) -> dict[str, Any]:
    """Current version of a decision in force (memory item or lineage id), governed and audited."""
    from app.context import expand

    async with _governed(ctx, on_behalf_of) as (scope, gov):
        result = await expand.get_memory(scope.session, gov, decision_id, decision_only=True)
        return {**result, **_untrusted_notice()}


async def get_memory_item(item_id: IdArg, ctx: Context, on_behalf_of: OnBehalfArg = None) -> dict[str, Any]:
    """Current version of any memory item (requirement, constraint, fact…), governed and audited."""
    from app.context import expand

    async with _governed(ctx, on_behalf_of) as (scope, gov):
        result = await expand.get_memory(scope.session, gov, item_id)
        return {**result, **_untrusted_notice()}


async def search_more(
    query: Annotated[str, Field(min_length=1, max_length=1000, description="Question complémentaire")],
    ctx: Context,
    limit: Annotated[int, Field(ge=1, le=30, description="Nombre maximal de résultats")] = 8,
    exclude_ids: Annotated[
        list[str] | None, Field(description="Identifiants déjà servis (index du contexte) à ignorer")
    ] = None,
    on_behalf_of: OnBehalfArg = None,
) -> dict[str, Any]:
    """Complementary governed search over sources and memory; each result says which tool expands it."""
    from app.context import expand

    async with _governed(ctx, on_behalf_of) as (scope, gov):
        results = await expand.search_more(
            scope.session, gov, query.strip(), limit=limit, exclude_ids=set(exclude_ids or [])
        )
        return {"results": results, **_untrusted_notice()}


async def _provenance_documents(scope: AgentScope, ids: Sequence[str]) -> list[Document]:
    """Resolve provenance documents; unknown and unreadable ones get the same message (non-leak)."""
    documents: list[Document] = []
    for raw in dict.fromkeys(ids):
        doc_id = _uuid(raw, "provenance_document_ids")
        document = await scope.session.get(Document, doc_id)
        if (
            document is None
            or document.project_id != scope.project.id
            or document.status == DocumentStatus.forgotten
            or not scope.visibility.allows(document.acl_principals, document.classification)
        ):
            raise ToolError(f"Document introuvable : {raw}")
        documents.append(document)
    return documents


async def hybrid_chunk_search(scope: AgentScope, query: str, limit: int) -> list[SearchHit]:
    """BM25 + k-NN over the project's chunks (``app.search.hybrid``), restricted to the agent's rights.

    The index pre-filter already applies ACL, clearance and ``active`` status; Postgres (the source
    of truth) is then re-checked for every hit so that a stale index entry can never leak content.
    """
    from app.search.hybrid import hybrid_search

    visibility = scope.visibility
    filters: list[Mapping[str, Any]] = [
        acl_terms_filter(visibility.principals),
        {"range": {"classification": {"lte": visibility.clearance}}},
        {"term": {"status": ChunkStatus.active.value}},
    ]
    try:
        fused = await hybrid_search(
            "chunks",
            query,
            None,
            project_id=scope.project.id,
            size_each=min(max(limit * 4, 20), 100),
            filters=filters,
            include_org_memory=False,
        )
    except NotImplementedError as exc:
        raise ToolError("Recherche indisponible : l'index des sources n'est pas encore opérationnel") from exc
    except Exception as exc:
        logger.warning("MCP search failed: %s", exc)
        raise ToolError("Recherche indisponible : le moteur d'indexation ne répond pas, réessayez") from exc

    ranked = [(uuid.UUID(hit.id), hit) for hit in fused if _is_uuid(hit.id)]
    if not ranked:
        return []
    rows = await scope.session.execute(
        select(Chunk, Document, Source.kind)
        .join(Document, Document.id == Chunk.document_id)
        .join(Source, Source.id == Document.source_id)
        .where(Chunk.id.in_([chunk_id for chunk_id, _ in ranked]), Chunk.project_id == scope.project.id)
    )
    by_id = {chunk.id: (chunk, document, kind) for chunk, document, kind in rows.tuples()}
    results: list[SearchHit] = []
    for chunk_id, hit in ranked:
        entry = by_id.get(chunk_id)
        if entry is None:
            continue
        chunk, document, kind = entry
        if (
            chunk.status != ChunkStatus.active
            or chunk.quarantined  # §A1: never served while in quarantine
            or document.status == DocumentStatus.forgotten
            or not visibility.allows(chunk.acl_principals, chunk.classification)
        ):
            continue
        results.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title,
                source_kind=kind,
                text=spotlight.wrap(chunk.text_redacted),  # §A2: untrusted data
                score=round(hit.rrf_norm, 4),
                bm25=hit.bm25_score,
                dense=hit.dense_score,
                section=chunk.section,
                source_updated_at=document.source_updated_at,
            )
        )
        if len(results) >= limit:
            break
    return results


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


async def snapshot_view(
    session: AsyncSession, snapshot: ContextSnapshot, visibility: Visibility
) -> dict[str, Any]:
    """``Snapshot`` payload restricted to what the agent may read.

    Items the agent cannot read are removed (neither title nor id is returned) and counted in
    ``restricted_items``; forgotten items keep their title but their excerpt is redacted. When
    anything was removed or redacted, ``content`` is rebuilt from the visible items only.
    """
    items: list[SnapshotItem] = []
    for raw in snapshot.items or []:
        try:
            items.append(SnapshotItem.model_validate(raw))
        except ValidationError:
            logger.warning("Snapshot %s@v%s: malformed item skipped", snapshot.name, snapshot.version)

    chunk_ids = {uuid.UUID(i.id) for i in items if i.candidate_type == CandidateType.chunk and _is_uuid(i.id)}
    memory_ids = {
        uuid.UUID(i.id) for i in items if i.candidate_type == CandidateType.memory and _is_uuid(i.id)
    }
    chunk_meta: dict[str, tuple[list[str], int, bool]] = {}
    if chunk_ids:
        rows = await session.execute(
            select(Chunk.id, Chunk.acl_principals, Chunk.classification, Chunk.status, Document.status)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(chunk_ids))
        )
        for cid, acl, level, status, doc_status in rows.tuples():
            forgotten = status == ChunkStatus.forgotten or doc_status == DocumentStatus.forgotten
            chunk_meta[str(cid)] = (list(acl), int(level), forgotten)
    memory_meta: dict[str, tuple[list[str], int, bool]] = {}
    if memory_ids:
        rows = await session.execute(
            select(
                MemoryItem.id, MemoryItem.acl_principals, MemoryItem.classification, MemoryItem.status
            ).where(MemoryItem.id.in_(memory_ids))
        )
        for mid, acl, level, status in rows.tuples():
            memory_meta[str(mid)] = (list(acl), int(level), status == MemoryStatus.forgotten)

    visible: list[SnapshotItem] = []
    restricted = 0
    redacted = False
    for item in items:
        if item.candidate_type == CandidateType.session:
            visible.append(item)
            continue
        meta = (chunk_meta if item.candidate_type == CandidateType.chunk else memory_meta).get(item.id)
        if meta is None or not visibility.allows(meta[0], meta[1]):
            restricted += 1
            continue
        if meta[2] or item.forgotten:
            item = item.model_copy(update={"excerpt": FORGOTTEN_EXCERPT, "forgotten": True})
            redacted = True
        visible.append(item)

    content = snapshot.content
    if restricted or redacted:
        header = (
            f"> Contenu reconstitué pour votre habilitation : {restricted} élément(s) non accessible(s) "
            "retiré(s), éléments oubliés caviardés."
        )
        body = "\n\n".join(f"[{i.citation}] **{i.title}**\n{i.excerpt}".strip() for i in visible)
        content = f"{header}\n\n{body}".strip()

    parent_version = None
    if snapshot.parent_id is not None:
        parent_version = await session.scalar(
            select(ContextSnapshot.version).where(ContextSnapshot.id == snapshot.parent_id)
        )
    label = ""
    if snapshot.created_by_id is not None:
        labels = await actor_labels(session, [(snapshot.created_by_type, snapshot.created_by_id)])
        label = labels.get(snapshot.created_by_id, "")
    elif snapshot.created_by_type == ActorType.system:
        label = audit.SYSTEM_LABEL

    view = Snapshot(
        id=snapshot.id,
        name=snapshot.name,
        version=snapshot.version,
        parent_version=parent_version,
        task=snapshot.task,
        intent=snapshot.intent,
        token_count=snapshot.token_count,
        items_count=len(visible),
        content_hash=snapshot.content_hash,
        created_by_label=label,
        created_at=snapshot.created_at,
        content=content,
        items=visible,
        request_id=snapshot.request_id,
    )
    data = view.model_dump(mode="json")
    if spotlight.enabled() and data.get("content") and not spotlight.is_wrapped(data["content"]):
        data["content"] = spotlight.wrap(data["content"])
    return {**data, "restricted_items": restricted, **_untrusted_notice()}


# --- Server & ASGI app --------------------------------------------------------------------------------

TOOL_SPECS: tuple[tuple[str, str, Any, ToolAnnotations], ...] = (
    (
        "get_context",
        "Assemble le contexte gouverné d'une tâche : décisions en vigueur, besoins, contraintes et extraits "
        "de sources cités [S1]…, filtrés selon les droits, la fraîcheur et la pertinence. Renvoie le texte, "
        "les citations, les compteurs d'exclusion par motif et le request_id.",
        get_context,
        ToolAnnotations(title="Obtenir un contexte gouverné", read_only_hint=False, open_world_hint=False),
    ),
    (
        "get_snapshot",
        "Relit une version d'un snapshot de contexte partagé (ex. spec-atlas@2), limité à vos droits.",
        get_snapshot,
        ToolAnnotations(title="Lire un snapshot de contexte", read_only_hint=True, open_world_hint=False),
    ),
    (
        "search_sources",
        "Recherche hybride (BM25 + sémantique) dans les documents indexés du projet ; données personnelles "
        "masquées, résultats limités à vos droits.",
        search_sources,
        ToolAnnotations(title="Rechercher dans les sources", read_only_hint=True, open_world_hint=False),
    ),
    (
        "propose_memory",
        "Propose un élément de mémoire projet (décision, besoin, contrainte, risque, fait…). "
        "Il reste « proposé » jusqu'à validation humaine.",
        propose_memory,
        ToolAnnotations(title="Proposer une mémoire", read_only_hint=False, idempotent_hint=False),
    ),
    (
        "record_turn",
        "Ajoute un tour (user, agent ou tool) à la mémoire court terme d'une session de travail.",
        record_turn,
        ToolAnnotations(title="Enregistrer un tour de session", read_only_hint=False, idempotent_hint=False),
    ),
    (
        "send_feedback",
        "Évalue (1 à 5) un contexte servi par get_context, à partir de son request_id.",
        send_feedback,
        ToolAnnotations(title="Évaluer un contexte", read_only_hint=False, idempotent_hint=False),
    ),
)

TOOL_SPECS = (
    *TOOL_SPECS,
    (
        "expand_source",
        "Contexte à la demande : texte complet d'un extrait (identifiant de l'index d'un contexte "
        "progressif) ou d'un document, filtré selon vos droits.",
        expand_source,
        ToolAnnotations(title="Déplier une source", read_only_hint=True, open_world_hint=False),
    ),
    (
        "get_decision",
        "Contexte à la demande : version en vigueur d'une décision (identifiant de l'index).",
        get_decision,
        ToolAnnotations(title="Lire une décision", read_only_hint=True, open_world_hint=False),
    ),
    (
        "get_memory_item",
        "Contexte à la demande : version en vigueur d'un élément de mémoire (besoin, contrainte, fait…).",
        get_memory_item,
        ToolAnnotations(title="Lire un élément de mémoire", read_only_hint=True, open_world_hint=False),
    ),
    (
        "search_more",
        "Recherche complémentaire gouvernée (sources et mémoire) ; chaque résultat indique l'outil qui "
        "renvoie son détail.",
        search_more,
        ToolAnnotations(title="Chercher davantage", read_only_hint=True, open_world_hint=False),
    ),
)

TOOL_NAMES: tuple[str, ...] = tuple(spec[0] for spec in TOOL_SPECS)


def build_mcp_server() -> MCPServer:
    """MCP server with the ORBIT tools (docs/API.md « MCP »)."""
    server: MCPServer = MCPServer(
        SERVER_NAME,
        title=SERVER_TITLE,
        description="Contexte et mémoire gouvernés : pertinence, fraîcheur, provenance, droits d'accès.",
        instructions=SERVER_INSTRUCTIONS,
        version=settings.app_version,
        log_level="WARNING",
    )
    for name, description, fn, hints in TOOL_SPECS:
        server.add_tool(fn, name=name, title=hints.title, description=description, annotations=hints)
    return server


def build_mcp_app() -> ASGIApp | None:
    """Streamable HTTP application served on ``/mcp`` (stateless, JSON responses, agent key required)."""
    server = build_mcp_server()
    app: Starlette = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        # Host/Origin allow-lists are not used: deployments are reached under varying host names (compose
        # service, reverse proxy) and every request must carry an agent key in a header that a
        # DNS-rebinding page cannot obtain or forge.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app.add_middleware(AgentKeyGate)
    return app
