"""A2A interoperability (docs/AI_CONTEXT_ENGINEERING.md §E5).

**Agent Card** — A2A protocol **0.3.0** (assumed offline from the published specification; no A2A SDK is
installed): served at ``/.well-known/agent-card.json`` (0.3 location) and ``/.well-known/agent.json``
(pre-0.3 location, kept as an alias). ORBIT is described as an agent exposing its context skills over
``HTTP+JSON`` (REST under ``/api/v1``) and MCP (``/mcp``), authenticated with an agent API key.

**Signed context handoff** — an agent (or user) of a project hands a snapshot over to another agent:

* ``POST /projects/{slug}/a2a/handoffs`` issues a compact **JWS (HS256)** whose claims reference the
  snapshot (id, name, version, content hash), the issuer, the audience, a unique ``jti`` and an expiry
  (``ORBIT_A2A_HANDOFF_TTL_SECONDS``); the key is ``ORBIT_A2A_SIGNING_SECRET`` (defaults to the JWT secret);
* ``POST /projects/{slug}/a2a/handoffs/receive`` verifies the signature (algorithm pinned), expiry,
  project, audience (``agent:<id>`` / ``user:<id>`` must match the caller), snapshot integrity (content hash)
  and **replay** (a ``jti`` is accepted once), then returns the snapshot **filtered by the receiver's
  rights**. Every issue, receipt and rejection is audited.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import jwt
from fastapi import APIRouter, Request, status
from pydantic import Field
from sqlalchemy import select

from app.config import settings
from app.context import snapshots as snapshot_service
from app.context.visibility import Viewer
from app.db import utcnow
from app.deps import AgentEditorAccess, AgentViewerAccess, ProjectAccess, SessionDep
from app.errors import ApiError, not_found
from app.models import A2AHandoff, ContextSnapshot
from app.schemas.common import ApiModel, InputModel
from app.services import audit
from app.services.audit import AuditAction

A2A_PROTOCOL_VERSION = "0.3.0"
ALGORITHM = "HS256"
KEY_ID = "orbit-a2a-hs256"
TOKEN_TYPE = "orbit-context-handoff+jwt"

router = APIRouter(prefix="/projects/{slug}/a2a", tags=["a2a"])
wellknown_router = APIRouter(tags=["a2a"])


def _secret() -> str:
    return settings.a2a_signing_secret or settings.jwt_secret


def _issuer(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _principal_ref(access: ProjectAccess) -> str:
    p = access.principal
    if p.agent is not None:
        return f"agent:{p.agent.id}"
    return f"user:{p.user.id}" if p.user is not None else "unknown"


def _disabled() -> ApiError:
    return ApiError(
        status.HTTP_404_NOT_FOUND, "A2A désactivé sur cette instance (ORBIT_A2A_ENABLED)", code="not_found"
    )


# --- Agent Card -------------------------------------------------------------------------------------


def agent_card(base_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    return {
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "name": "ORBIT",
        "description": (
            "Contexte et mémoire gouvernés pour agents IA : contexte pertinent, frais, sourcé et filtré "
            "selon les droits ; mémoire projet ; snapshots partagés et passation signée entre agents."
        ),
        "url": f"{base}/api/v1",
        "preferredTransport": "HTTP+JSON",
        "additionalInterfaces": [
            {"url": f"{base}/api/v1", "transport": "HTTP+JSON"},
            {"url": f"{base}/mcp", "transport": "MCP"},
        ],
        "provider": {"organization": "ORBIT", "url": base},
        "version": settings.app_version,
        "documentationUrl": f"{base}/api/v1/docs",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
        "securitySchemes": {
            "orbitAgentKey": {
                "type": "http",
                "scheme": "bearer",
                "description": "Clé d'agent ORBIT (Authorization: Bearer orb_…, ou en-tête X-Orbit-Key)",
            }
        },
        "security": [{"orbitAgentKey": []}],
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json", "text/markdown"],
        "skills": [
            {
                "id": "governed-context",
                "name": "Contexte gouverné",
                "description": "Assemble un contexte cité pour une tâche (POST /projects/{slug}/context).",
                "tags": ["context", "rag", "governance"],
                "examples": ["Prépare le contexte pour rédiger la spécification du portail Atlas"],
            },
            {
                "id": "project-memory",
                "name": "Mémoire projet",
                "description": "Décisions, exigences, contraintes et skills du projet (MCP resources orbit://…).",
                "tags": ["memory", "decisions", "skills"],
            },
            {
                "id": "context-handoff",
                "name": "Passation de contexte signée",
                "description": (
                    "Remet un snapshot à un autre agent par jeton JWS HS256 vérifié à la réception "
                    "(POST /projects/{slug}/a2a/handoffs, …/handoffs/receive)."
                ),
                "tags": ["a2a", "handoff", "snapshot"],
            },
        ],
    }


async def _card(request: Request) -> dict[str, Any]:
    if not settings.a2a_enabled:
        raise _disabled()
    return agent_card(_issuer(request))


wellknown_router.add_api_route(
    "/.well-known/agent-card.json", _card, methods=["GET"], summary="Agent Card A2A (0.3)"
)
wellknown_router.add_api_route(
    "/.well-known/agent.json", _card, methods=["GET"], summary="Agent Card A2A (alias pré-0.3)"
)


# --- Signed handoff ---------------------------------------------------------------------------------


class HandoffIn(InputModel):
    snapshot: str = Field(min_length=1, max_length=140, description="Nom du snapshot, ou nom@version")
    audience: str = Field(min_length=1, max_length=300, description="agent:<id>, user:<id> ou URL de l'agent")


class HandoffOut(ApiModel):
    handoff_id: uuid.UUID
    token: str
    expires_at: Any
    snapshot: dict[str, Any]


class ReceiveIn(InputModel):
    token: str = Field(min_length=10, max_length=8000)


def sign(claims: dict[str, Any]) -> str:
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM, headers={"kid": KEY_ID, "typ": TOKEN_TYPE})


@router.post("/handoffs", response_model=HandoffOut, status_code=status.HTTP_201_CREATED, summary="Émettre")
async def issue_handoff(
    body: HandoffIn, request: Request, access: AgentEditorAccess, session: SessionDep
) -> HandoffOut:
    if not settings.a2a_enabled:
        raise _disabled()
    name, _, raw_version = body.snapshot.partition("@")
    version = snapshot_service.parse_version(raw_version or "latest")
    snapshot = await snapshot_service.get_snapshot(
        session, access.project_id, name.strip(), version or "latest"
    )
    if snapshot is None:
        raise not_found(f"Snapshot « {body.snapshot} » introuvable")
    now = utcnow()
    expires = now + timedelta(seconds=settings.a2a_handoff_ttl_seconds)
    jti = uuid.uuid4().hex
    ref = {"id": str(snapshot.id), "name": snapshot.name, "version": snapshot.version}
    claims = {
        "iss": _issuer(request),
        "sub": _principal_ref(access),
        "aud": body.audience,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "project": access.project.slug,
        "snapshot": {**ref, "content_hash": snapshot.content_hash},
    }
    row = A2AHandoff(
        project_id=access.project_id,
        jti=jti,
        snapshot_id=snapshot.id,
        issuer=claims["sub"],
        audience=body.audience,
        expires_at=expires,
    )
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.a2a_handoff_issue,
        "snapshot",
        f"{snapshot.name}@v{snapshot.version}",
        summary=f"Passation signée du snapshot « {snapshot.name} » v{snapshot.version} vers {body.audience}",
        details={
            "handoff_id": row.id,
            "jti": jti,
            "audience": body.audience,
            "expires_at": expires.isoformat(),
        },
    )
    await session.commit()
    return HandoffOut(handoff_id=row.id, token=sign(claims), expires_at=expires, snapshot=ref)


async def _reject(
    session: Any, access: ProjectAccess, reason: str, status_code: int, jti: str | None
) -> ApiError:
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.a2a_handoff_reject,
        "a2a_handoff",
        jti,
        summary=f"Passation refusée : {reason}",
        details={"reason": reason, "jti": jti},
    )
    await session.commit()
    return ApiError(status_code, f"Passation refusée : {reason}", code="handoff_rejected")


@router.post("/handoffs/receive", summary="Recevoir une passation (vérification de la signature)")
async def receive_handoff(
    body: ReceiveIn, request: Request, access: AgentViewerAccess, session: SessionDep
) -> dict[str, Any]:
    if not settings.a2a_enabled:
        raise _disabled()
    try:
        header = jwt.get_unverified_header(body.token)
        claims = jwt.decode(
            body.token,
            _secret(),
            algorithms=[ALGORITHM],
            options={"verify_aud": False, "require": ["exp", "iat", "jti", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError:
        raise await _reject(session, access, "jeton expiré", status.HTTP_401_UNAUTHORIZED, None) from None
    except jwt.PyJWTError:
        raise await _reject(
            session, access, "signature invalide", status.HTTP_401_UNAUTHORIZED, None
        ) from None
    jti = str(claims.get("jti"))
    if header.get("typ") != TOKEN_TYPE or claims.get("project") != access.project.slug:
        raise await _reject(session, access, "jeton d'un autre projet ou d'un autre type", 403, jti)
    audience = str(claims.get("aud"))
    if audience.startswith(("agent:", "user:")) and audience != _principal_ref(access):
        raise await _reject(session, access, "destinataire différent", status.HTTP_403_FORBIDDEN, jti)
    row = await session.scalar(
        select(A2AHandoff)
        .where(A2AHandoff.jti == jti, A2AHandoff.project_id == access.project_id)
        .with_for_update()
    )
    if row is None:
        raise await _reject(session, access, "passation inconnue", status.HTTP_401_UNAUTHORIZED, jti)
    if row.received_at is not None:
        raise await _reject(session, access, "jeton déjà utilisé (rejeu)", status.HTTP_409_CONFLICT, jti)
    ref = claims.get("snapshot") or {}
    snapshot = await session.get(ContextSnapshot, row.snapshot_id)
    if (
        snapshot is None
        or str(snapshot.id) != ref.get("id")
        or snapshot.content_hash != ref.get("content_hash")
    ):
        raise await _reject(session, access, "snapshot modifié ou introuvable", status.HTTP_409_CONFLICT, jti)
    row.received_at = utcnow()
    row.received_by = _principal_ref(access)
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.a2a_handoff_receive,
        "snapshot",
        f"{snapshot.name}@v{snapshot.version}",
        summary=f"Passation reçue : snapshot « {snapshot.name} » v{snapshot.version}",
        details={"handoff_id": row.id, "jti": jti, "issuer": row.issuer},
    )
    view = await snapshot_service.present(session, snapshot, Viewer.from_access(access))
    await session.commit()
    return {
        "verified": True,
        "handoff_id": str(row.id),
        "issuer": row.issuer,
        "issued_by": claims.get("iss"),
        "snapshot": view.model_dump(mode="json"),
    }
