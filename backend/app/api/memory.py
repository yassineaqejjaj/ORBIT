"""Governed memory (STUB — implemented by the memory teammate). See ``app.memory.lifecycle``.

Route order matters: ``/memory/graph`` and ``/memory/consolidate`` are declared before
``/memory/{memory_id}``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.deps import AgentEditorAccess, EditorAccess, SessionDep, ViewerAccess
from app.enums import MemoryKind, MemoryScope, MemoryStatus
from app.schemas import (
    Job,
    MemoryDetail,
    MemoryGraph,
    MemoryIn,
    MemoryItem,
    MemoryUpdateIn,
    Page,
    PageParams,
    ReasonIn,
    ReasonRequiredIn,
    SupersedeIn,
    page_params,
)

router = APIRouter(prefix="/projects/{slug}/memory", tags=["memory"])


@router.get(
    "", response_model=Page[MemoryItem], summary="Items mémoire (versions courantes, filtrés par droits)"
)
async def list_memory(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    scope: MemoryScope | None = Query(default=None),
    kind: MemoryKind | None = Query(default=None),
    status_: MemoryStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    include_history: bool = Query(default=False),
) -> Page[MemoryItem]:
    raise NotImplementedError


@router.post(
    "", response_model=MemoryItem, status_code=status.HTTP_201_CREATED, summary="Créer un item mémoire"
)
async def create_memory(body: MemoryIn, access: AgentEditorAccess, session: SessionDep) -> MemoryItem:
    raise NotImplementedError


@router.post("/consolidate", response_model=Job, summary="Lancer une consolidation mémoire")
async def consolidate_memory(access: EditorAccess, session: SessionDep) -> Job:
    raise NotImplementedError


@router.get("/graph", response_model=MemoryGraph, summary="Graphe mémoire")
async def memory_graph(
    access: ViewerAccess, session: SessionDep, limit: int = Query(default=150, ge=1, le=1000)
) -> MemoryGraph:
    raise NotImplementedError


@router.get("/{memory_id}", response_model=MemoryDetail, summary="Détail d'un item mémoire")
async def get_memory(memory_id: uuid.UUID, access: ViewerAccess, session: SessionDep) -> MemoryDetail:
    raise NotImplementedError


@router.patch("/{memory_id}", response_model=MemoryItem, summary="Modifier (crée une nouvelle version)")
async def update_memory(
    memory_id: uuid.UUID, body: MemoryUpdateIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    raise NotImplementedError


@router.post("/{memory_id}/validate", response_model=MemoryItem, summary="Valider")
async def validate_memory(
    memory_id: uuid.UUID, body: ReasonIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    raise NotImplementedError


@router.post("/{memory_id}/obsolete", response_model=MemoryItem, summary="Marquer obsolète")
async def obsolete_memory(
    memory_id: uuid.UUID, body: ReasonRequiredIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    raise NotImplementedError


@router.post("/{memory_id}/supersede", response_model=MemoryItem, summary="Remplacer par un autre item")
async def supersede_memory(
    memory_id: uuid.UUID, body: SupersedeIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    raise NotImplementedError


@router.post("/{memory_id}/restore", response_model=MemoryItem, summary="Restaurer")
async def restore_memory(
    memory_id: uuid.UUID, body: ReasonIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    raise NotImplementedError


@router.post(
    "/{memory_id}/forget",
    response_model=MemoryItem,
    summary="Oubli sélectif (owner, ou sujet pour la portée user)",
)
async def forget_memory(
    memory_id: uuid.UUID, body: ReasonRequiredIn, access: ViewerAccess, session: SessionDep
) -> MemoryItem:
    """Access check inside: owner, or the subject user for ``scope=user`` items."""
    raise NotImplementedError
