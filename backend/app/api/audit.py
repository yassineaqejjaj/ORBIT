"""Project audit trail."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import SessionDep, ViewerAccess
from app.schemas import AuditEvent, Page, PageParams, make_page, page_params
from app.services import audit as audit_service

router = APIRouter(prefix="/projects/{slug}/audit", tags=["audit"])


@router.get("", response_model=Page[AuditEvent], summary="Journal d'audit du projet")
async def list_audit(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    action: str | None = Query(
        default=None, max_length=100, description="Action exacte ou domaine (ex. memory)"
    ),
) -> Page[AuditEvent]:
    rows, total = await audit_service.list_events(
        session, access.project_id, action=action, offset=params.offset, limit=params.limit
    )
    items = [
        AuditEvent.model_validate(row).model_copy(
            update={
                "details": audit_service.visible_details(
                    row.details, can_see_restricted=access.can_see_restricted_details
                )
            }
        )
        for row in rows
    ]
    return make_page(items, total, params)
