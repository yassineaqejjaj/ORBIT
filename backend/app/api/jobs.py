"""Ingestion jobs of a project (jobs of documents the caller cannot see are hidden)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.deps import SessionDep, ViewerAccess
from app.enums import JobStatus
from app.ingestion.service import DocumentViewer
from app.models import Document, IngestionJob
from app.schemas import JobWithDocument, Page, PageParams, page_params
from app.schemas.common import make_page

router = APIRouter(prefix="/projects/{slug}/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobWithDocument], summary="Jobs d'ingestion du projet")
async def list_jobs(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    status_: JobStatus | None = Query(default=None, alias="status"),
) -> Page[JobWithDocument]:
    viewer = DocumentViewer.from_access(access)
    conditions = [
        IngestionJob.project_id == access.project_id,
        or_(IngestionJob.document_id.is_(None), viewer.clause()),
    ]
    if status_ is not None:
        conditions.append(IngestionJob.status == status_)
    base = select(IngestionJob, Document.title).outerjoin(Document, Document.id == IngestionJob.document_id)
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(IngestionJob)
            .outerjoin(Document, Document.id == IngestionJob.document_id)
            .where(*conditions)
        )
        or 0
    )
    rows = await session.execute(
        base.where(*conditions)
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id)
        .offset(params.offset)
        .limit(params.limit)
    )
    items = [
        JobWithDocument.model_validate(job).model_copy(update={"document_title": title})
        for job, title in rows.tuples()
    ]
    return make_page(items, total, params)
