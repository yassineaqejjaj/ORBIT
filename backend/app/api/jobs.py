"""Ingestion jobs (STUB — implemented by the ingestion teammate)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import SessionDep, ViewerAccess
from app.enums import JobStatus
from app.schemas import JobWithDocument, Page, PageParams, page_params

router = APIRouter(prefix="/projects/{slug}/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobWithDocument], summary="Jobs d'ingestion du projet")
async def list_jobs(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    status_: JobStatus | None = Query(default=None, alias="status"),
) -> Page[JobWithDocument]:
    raise NotImplementedError
