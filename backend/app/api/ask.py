"""« Demander à ORBIT » (F4, docs/FEATURES.md): cited answers on top of the governed context engine."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from app.deps import AgentViewerAccess, SessionDep
from app.features.ask import service
from app.features.ask.schemas import (
    AskConversationDetail,
    AskConversationSummary,
    AskFeedbackIn,
    AskIn,
    AskMessageOut,
    AskOut,
)

router = APIRouter(prefix="/projects/{slug}/ask", tags=["ask"])


@router.post("", response_model=AskOut, summary="Poser une question à ORBIT (réponse citée)")
async def ask(body: AskIn, access: AgentViewerAccess, session: SessionDep) -> AskOut:
    """Same governance as ``POST /context`` (ACL, habilitation, mémoire privée, caviardage PII)."""
    channel = "api" if access.principal.is_agent else "web"
    return await service.ask(session, access, body, channel=channel)


@router.get(
    "/conversations", response_model=list[AskConversationSummary], summary="Mes conversations avec ORBIT"
)
async def list_conversations(
    access: AgentViewerAccess, session: SessionDep, limit: int = Query(default=50, ge=1, le=200)
) -> list[AskConversationSummary]:
    return await service.list_conversations(session, access, limit=limit)


@router.get(
    "/conversations/{conversation_id}", response_model=AskConversationDetail, summary="Conversation détaillée"
)
async def get_conversation(
    conversation_id: uuid.UUID, access: AgentViewerAccess, session: SessionDep
) -> AskConversationDetail:
    return await service.conversation_detail(session, access, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=204, summary="Supprimer une conversation")
async def delete_conversation(
    conversation_id: uuid.UUID, access: AgentViewerAccess, session: SessionDep
) -> Response:
    await service.delete_conversation(session, access, conversation_id)
    return Response(status_code=204)


@router.post(
    "/messages/{message_id}/feedback", response_model=AskMessageOut, summary="Évaluer une réponse (👍/👎)"
)
async def send_feedback(
    message_id: uuid.UUID, body: AskFeedbackIn, access: AgentViewerAccess, session: SessionDep
) -> AskMessageOut:
    return await service.send_feedback(session, access, message_id, body)
