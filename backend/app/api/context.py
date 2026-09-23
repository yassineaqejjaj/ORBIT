"""Context assembly endpoints (STUB — implemented by the context teammate). See ``app.context.assembler``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import AgentViewerAccess, SessionDep, ViewerAccess
from app.schemas import (
    ContextPackage,
    ContextRequestDetail,
    ContextRequestIn,
    ContextRequestSummary,
    FeedbackIn,
    IdOut,
    Page,
    PageParams,
    page_params,
)

router = APIRouter(prefix="/projects/{slug}/context", tags=["context"])


@router.post("", response_model=ContextPackage, summary="Assembler un contexte gouverné")
async def request_context(
    body: ContextRequestIn, access: AgentViewerAccess, session: SessionDep
) -> ContextPackage:
    raise NotImplementedError


@router.get(
    "/requests", response_model=Page[ContextRequestSummary], summary="Historique des requêtes de contexte"
)
async def list_context_requests(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    agent_id: uuid.UUID | None = Query(default=None),
) -> Page[ContextRequestSummary]:
    raise NotImplementedError


@router.get(
    "/requests/{request_id}", response_model=ContextRequestDetail, summary="Requête de contexte reconstituée"
)
async def get_context_request(
    request_id: uuid.UUID, access: ViewerAccess, session: SessionDep
) -> ContextRequestDetail:
    raise NotImplementedError


@router.post("/requests/{request_id}/feedback", response_model=IdOut, summary="Évaluer un contexte servi")
async def send_feedback(
    request_id: uuid.UUID, body: FeedbackIn, access: AgentViewerAccess, session: SessionDep
) -> IdOut:
    raise NotImplementedError
