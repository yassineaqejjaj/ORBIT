"""Business sources (STUB — implemented by the ingestion teammate).

Endpoints (docs/API.md « Sources & documents »): list with per-source ``counts``, create, patch.
Audit actions: ``source.create`` / ``source.update``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.deps import EditorAccess, SessionDep, ViewerAccess
from app.schemas import Source, SourceCreateIn, SourceUpdateIn

router = APIRouter(prefix="/projects/{slug}/sources", tags=["sources"])


@router.get("", response_model=list[Source], summary="Sources du projet")
async def list_sources(access: ViewerAccess, session: SessionDep) -> list[Source]:
    raise NotImplementedError


@router.post("", response_model=Source, status_code=status.HTTP_201_CREATED, summary="Créer une source")
async def create_source(body: SourceCreateIn, access: EditorAccess, session: SessionDep) -> Source:
    raise NotImplementedError


@router.patch("/{source_id}", response_model=Source, summary="Modifier une source")
async def update_source(
    source_id: uuid.UUID, body: SourceUpdateIn, access: EditorAccess, session: SessionDep
) -> Source:
    raise NotImplementedError
