"""Ingestion jobs of a project (jobs of documents the caller cannot see are hidden).

Editors may retry (``failed`` / ``dead`` / ``cancelled``) and cancel jobs; both actions are audited.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import EditorAccess, ProjectAccess, SessionDep, ViewerAccess
from app.enums import JobStatus
from app.errors import ApiError, not_found
from app.ingestion import queue
from app.ingestion.service import DocumentViewer
from app.models import Document, IngestionJob
from app.schemas import JobWithDocument, Page, PageParams, page_params
from app.schemas.common import make_page
from app.services import audit

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


# --- Operator actions -------------------------------------------------------------------------------------

AUDIT_JOB_RETRY = "job.retry"
AUDIT_JOB_CANCEL = "job.cancel"


async def _visible_job(
    access: ProjectAccess, session: AsyncSession, job_id: uuid.UUID
) -> tuple[IngestionJob, str | None]:
    """Job of the project whose document (if any) the caller may see — 404 otherwise."""
    viewer = DocumentViewer.from_access(access)
    row = (
        await session.execute(
            select(IngestionJob, Document.title)
            .outerjoin(Document, Document.id == IngestionJob.document_id)
            .where(
                IngestionJob.id == job_id,
                IngestionJob.project_id == access.project_id,
                or_(IngestionJob.document_id.is_(None), viewer.clause()),
            )
            .with_for_update(of=IngestionJob)
        )
    ).first()
    if row is None:
        raise not_found("Job introuvable")
    return row[0], row[1]


def _job_out(job: IngestionJob, title: str | None) -> JobWithDocument:
    return JobWithDocument.model_validate(job).model_copy(update={"document_title": title})


@router.post(
    "/{job_id}/retry",
    response_model=JobWithDocument,
    summary="Relancer un job en échec, en file morte ou annulé",
)
async def retry(job_id: uuid.UUID, access: EditorAccess, session: SessionDep) -> JobWithDocument:
    job, title = await _visible_job(access, session, job_id)
    previous = job.status
    try:
        await queue.retry_job(session, job)
    except queue.JobStateError as exc:
        raise ApiError(409, str(exc), code="job_not_retryable") from exc
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AUDIT_JOB_RETRY,
        "job",
        job.id,
        summary=f"Relance du job {job.kind} (statut précédent : {previous})",
        details={"kind": str(job.kind), "previous_status": str(previous), "document_id": job.document_id},
    )
    await session.commit()
    return _job_out(job, title)


@router.post("/{job_id}/cancel", response_model=JobWithDocument, summary="Annuler un job")
async def cancel(job_id: uuid.UUID, access: EditorAccess, session: SessionDep) -> JobWithDocument:
    """A queued or failed job is cancelled at once; a running job is stopped by its worker at the
    next heartbeat (the response then still shows ``running``)."""
    job, title = await _visible_job(access, session, job_id)
    previous = job.status
    try:
        await queue.cancel_job(session, job, reason=f"Annulé par {access.principal.label}")
    except queue.JobStateError as exc:
        raise ApiError(409, str(exc), code="job_not_cancellable") from exc
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AUDIT_JOB_CANCEL,
        "job",
        job.id,
        summary=f"Annulation du job {job.kind} (statut précédent : {previous})",
        details={"kind": str(job.kind), "previous_status": str(previous), "document_id": job.document_id},
    )
    await session.commit()
    return _job_out(job, title)
