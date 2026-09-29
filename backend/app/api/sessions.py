"""Short-term memory sessions (docs/API.md « Sessions », ARCHITECTURE §8).

Agent turns are buffered in Valkey (``app.memory.short_term``) with the project's
``short_term_ttl_hours`` TTL, refreshed on every turn. Closing a session consolidates it into a
project ``summary`` item (``app.memory.consolidation.close_session``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable

from fastapi import APIRouter, Path, status
from sqlalchemy import select

from app.deps import AgentEditorAccess, AgentViewerAccess, ProjectAccess, SessionDep
from app.errors import ApiError, not_found, validation_error
from app.memory import consolidation, short_term
from app.memory.serializers import serialize_item, serialize_items
from app.memory.visibility import MemoryViewer, visibility_clause
from app.models import Agent
from app.models import MemoryItem as MemoryItemRow
from app.schemas import SessionCloseOut, SessionDetail, SessionSummary, TurnAppendOut, TurnIn
from app.schemas.sessions import SessionTurn
from app.services import projects as project_service

logger = logging.getLogger("orbit.api.sessions")

router = APIRouter(prefix="/projects/{slug}/sessions", tags=["sessions"])

SessionIdPath = Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:\-]+$")
SESSION_NOT_FOUND = "Session introuvable ou expirée"
SESSION_ITEMS_LIMIT = 100


async def _valkey[T](operation: Awaitable[T]) -> T:
    """Run a Valkey operation; an unavailable store answers 503 with a French message."""
    try:
        return await operation
    except (ConnectionError, OSError, TimeoutError) as exc:
        logger.warning("Valkey unavailable: %s", exc)
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Mémoire court terme indisponible (Valkey injoignable), réessayez dans un instant",
            code="unavailable",
        ) from exc
    except Exception as exc:
        if exc.__class__.__module__.startswith(("redis", "valkey")):
            logger.warning("Valkey error: %s", exc)
            raise ApiError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Mémoire court terme indisponible (Valkey injoignable), réessayez dans un instant",
                code="unavailable",
            ) from exc
        raise


async def _ttl_hours(access: ProjectAccess) -> int:
    return int(project_service.normalize_settings(access.project.settings)["short_term_ttl_hours"])


@router.get("", response_model=list[SessionSummary], summary="Sessions actives")
async def list_sessions(access: AgentViewerAccess, session: SessionDep) -> list[SessionSummary]:
    infos = await _valkey(short_term.list_sessions(access.project_id))
    return [
        SessionSummary(
            session_id=info.session_id,
            turns=info.turns,
            updated_at=info.updated_at,
            expires_at=info.expires_at,
        )
        for info in infos
    ]


@router.post("/{session_id}/turns", response_model=TurnAppendOut, summary="Ajouter un tour de session")
async def append_turn(
    body: TurnIn, access: AgentEditorAccess, session: SessionDep, session_id: str = SessionIdPath
) -> TurnAppendOut:
    principal = access.principal
    agent_id: uuid.UUID | None = principal.agent_id
    if agent_id is None and body.agent_id is not None:
        agent = await session.get(Agent, body.agent_id)
        if agent is None or agent.project_id != access.project_id:
            raise validation_error("Agent introuvable dans ce projet")
        agent_id = agent.id
    count, expires_at = await _valkey(
        short_term.append_turn(
            access.project_id,
            session_id,
            body.role,
            body.content,
            ttl_hours=await _ttl_hours(access),
            agent_id=agent_id,
        )
    )
    return TurnAppendOut(session_id=session_id, turns=count, expires_at=expires_at)


async def _session_items(session: SessionDep, access: ProjectAccess, session_id: str) -> list[MemoryItemRow]:
    rows = await session.scalars(
        select(MemoryItemRow)
        .where(
            visibility_clause(MemoryViewer.from_access(access)),
            MemoryItemRow.project_id == access.project_id,
            MemoryItemRow.session_id == session_id,
            MemoryItemRow.is_current.is_(True),
        )
        .order_by(MemoryItemRow.created_at.desc())
        .limit(SESSION_ITEMS_LIMIT)
    )
    return list(rows)


@router.get("/{session_id}", response_model=SessionDetail, summary="Détail d'une session")
async def get_session_detail(
    access: AgentViewerAccess, session: SessionDep, session_id: str = SessionIdPath
) -> SessionDetail:
    turns = await _valkey(short_term.get_turns(access.project_id, session_id))
    expires_at = await _valkey(short_term.get_expiry(access.project_id, session_id)) if turns else None
    items = await _session_items(session, access, session_id)
    if not turns and not items:
        raise not_found(SESSION_NOT_FOUND)
    return SessionDetail(
        session_id=session_id,
        turns=[SessionTurn(role=turn.role, content=turn.content, at=turn.at) for turn in turns],
        expires_at=expires_at,
        memory_items=await serialize_items(session, items),
    )


@router.post("/{session_id}/close", response_model=SessionCloseOut, summary="Clore et consolider la session")
async def close_session(
    access: AgentEditorAccess, session: SessionDep, session_id: str = SessionIdPath
) -> SessionCloseOut:
    turns = await _valkey(short_term.get_turns(access.project_id, session_id))
    items = await _session_items(session, access, session_id)
    if not turns and not items:
        raise not_found(SESSION_NOT_FOUND)
    summary = await consolidation.close_session(
        session, access.project_id, session_id, access.principal.actor, turns=turns, clear=False
    )
    await session.commit()
    await _valkey(short_term.clear_session(access.project_id, session_id))
    return SessionCloseOut(summary=await serialize_item(session, summary) if summary is not None else None)


__all__ = ["router"]
