"""Short-term memory sessions (STUB — implemented by the memory teammate). See ``app.memory.short_term``."""

from __future__ import annotations

from fastapi import APIRouter, Path

from app.deps import AgentEditorAccess, AgentViewerAccess, SessionDep
from app.schemas import SessionCloseOut, SessionDetail, SessionSummary, TurnAppendOut, TurnIn

router = APIRouter(prefix="/projects/{slug}/sessions", tags=["sessions"])

SessionIdPath = Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9._:\-]+$")


@router.get("", response_model=list[SessionSummary], summary="Sessions actives")
async def list_sessions(access: AgentViewerAccess, session: SessionDep) -> list[SessionSummary]:
    raise NotImplementedError


@router.post("/{session_id}/turns", response_model=TurnAppendOut, summary="Ajouter un tour de session")
async def append_turn(
    body: TurnIn, access: AgentEditorAccess, session: SessionDep, session_id: str = SessionIdPath
) -> TurnAppendOut:
    raise NotImplementedError


@router.get("/{session_id}", response_model=SessionDetail, summary="Détail d'une session")
async def get_session_detail(
    access: AgentViewerAccess, session: SessionDep, session_id: str = SessionIdPath
) -> SessionDetail:
    raise NotImplementedError


@router.post("/{session_id}/close", response_model=SessionCloseOut, summary="Clore et consolider la session")
async def close_session(
    access: AgentEditorAccess, session: SessionDep, session_id: str = SessionIdPath
) -> SessionCloseOut:
    raise NotImplementedError
