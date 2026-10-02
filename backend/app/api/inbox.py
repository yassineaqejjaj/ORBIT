"""Memory triage inbox & conflict arbitration (docs/FEATURES.md F1).

Same governance as ``/memory``: only items visible to the caller (ACL, clearance, private user
memory) are listed or changed; a conflict is shown only when both sides are visible.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.deps import EditorAccess, SessionDep, ViewerAccess
from app.enums import MemoryKind
from app.features.inbox import service
from app.features.inbox.schemas import BulkIn, BulkOut, Conflict, DismissIn, InboxCount, InboxItem, ResolveIn
from app.memory.visibility import MemoryViewer
from app.schemas import Page, PageParams, page_params
from app.schemas.common import make_page

router = APIRouter(prefix="/projects/{slug}", tags=["inbox"])


@router.get("/inbox", response_model=Page[InboxItem], summary="Propositions mémoire à trier")
async def list_inbox(
    access: EditorAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    kind: MemoryKind | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    sort: Literal["impact", "confidence", "recent"] = Query(default="impact"),
) -> Page[InboxItem]:
    items, total = await service.list_proposals(
        session,
        MemoryViewer.from_access(access),
        kind=kind,
        min_confidence=min_confidence,
        sort=sort,
        offset=params.offset,
        limit=params.limit,
    )
    return make_page(items, total, params)


@router.get("/inbox/count", response_model=InboxCount, summary="Compteur du tri (badge de navigation)")
async def inbox_count(access: EditorAccess, session: SessionDep) -> InboxCount:
    viewer = MemoryViewer.from_access(access)
    proposals = await service.count_proposals(session, viewer)
    conflicts = await service.count_open_conflicts(session, viewer)
    return InboxCount(proposals=proposals, conflicts=conflicts, total=proposals + conflicts)


@router.post("/inbox/bulk", response_model=BulkOut, summary="Action groupée (valider, rejeter, fusionner)")
async def bulk_inbox(body: BulkIn, access: EditorAccess, session: SessionDep) -> BulkOut:
    return await service.bulk(session, access, body)


@router.get("/conflicts", response_model=list[Conflict], summary="Contradictions entre items mémoire")
async def list_conflicts(
    access: ViewerAccess,
    session: SessionDep,
    status: Literal["open", "resolved"] = Query(default="open"),
) -> list[Conflict]:
    return await service.list_conflicts(session, MemoryViewer.from_access(access), status)


@router.post(
    "/conflicts/{conflict_id}/resolve", response_model=Conflict, summary="Arbitrer une contradiction"
)
async def resolve_conflict(
    conflict_id: uuid.UUID, body: ResolveIn, access: EditorAccess, session: SessionDep
) -> Conflict:
    return await service.resolve(session, access, conflict_id, body.winner_id, body.reason)


@router.post("/conflicts/{conflict_id}/dismiss", response_model=Conflict, summary="Pas une contradiction")
async def dismiss_conflict(
    conflict_id: uuid.UUID, body: DismissIn, access: EditorAccess, session: SessionDep
) -> Conflict:
    return await service.dismiss(session, access, conflict_id, body.reason)


__all__ = ["router"]
