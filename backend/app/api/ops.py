"""Operations endpoints (docs/PRODUCTION.md §3 « Exploitation ») — platform administrators only.

* ``GET /ops/status`` — queue backlog (by status and kind), workers (heartbeats), dependencies,
  search indices, cluster-wide scheduled tasks (last maintenance / retention run);
* ``GET /ops/jobs/dead-letter`` — ``dead`` jobs (retries exhausted or poison pill), newest first.

Retry / cancel of a job are project-scoped actions: ``POST /projects/{slug}/jobs/{id}/retry|cancel``
(:mod:`app.api.jobs`). Titles and errors of documents classified above the administrator's clearance
are masked: operating the platform does not grant access to restricted content.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.deps import AdminUser, SessionDep
from app.enums import JobKind, JobStatus
from app.errors import not_found
from app.ingestion.queue import queue_stats
from app.models import Document, IngestionJob, Project
from app.models.job import ScheduledTask, WorkerHeartbeat
from app.observability.health import DependencyStatus, check_core_dependencies
from app.schemas import Page, PageParams, page_params
from app.schemas.common import ApiModel, make_page
from app.schemas.documents import JobStep

router = APIRouter(prefix="/ops", tags=["ops"])

RESTRICTED_TITLE = "Document restreint"
RESTRICTED_ERROR = "Détail masqué (document au-delà de votre habilitation)"


# --- Schemas ----------------------------------------------------------------------------------------------


class QueueStatus(ApiModel):
    totals: dict[str, int] = Field(description="Nombre de jobs par statut")
    by_status: dict[str, dict[str, int]] = Field(description="{statut: {type de job: nombre}}")
    oldest_queued_age_seconds: dict[str, float] = Field(
        description="Âge du plus ancien job exécutable, par type"
    )
    dead_letter: int


class WorkerStatus(ApiModel):
    worker_id: str
    hostname: str
    pid: int
    version: str
    concurrency: int
    in_flight: int
    stats: dict[str, Any]
    started_at: datetime
    last_seen_at: datetime
    stopping: bool
    alive: bool = Field(default=False, description="Heartbeat reçu récemment (moins de 3 intervalles)")


class DependencyOut(ApiModel):
    name: str
    status: str
    required: bool
    latency_ms: float | None = None
    detail: str | None = None
    info: dict[str, Any] = Field(default_factory=dict)


class IndexStatus(ApiModel):
    kind: str
    name: str
    documents: int | None = None
    error: str | None = None


class ScheduledTaskOut(ApiModel):
    name: str
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_status: str
    last_error: str | None
    last_summary: dict[str, Any]
    holder: str | None


class OpsStatus(ApiModel):
    status: str = Field(description="ok | degraded (dépendance requise indisponible ou aucun worker actif)")
    generated_at: datetime
    version: str
    queue: QueueStatus
    workers: list[WorkerStatus]
    dependencies: list[DependencyOut]
    indices: list[IndexStatus]
    scheduled_tasks: list[ScheduledTaskOut]


class DeadLetterJob(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    project_slug: str | None = None
    project_name: str | None = None
    document_id: uuid.UUID | None
    document_title: str | None = None
    kind: JobKind
    status: JobStatus
    priority: int
    attempts: int
    max_attempts: int
    crash_count: int
    error: str | None
    steps: list[JobStep]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# --- Helpers ----------------------------------------------------------------------------------------------


def _heartbeat_staleness() -> timedelta:
    return timedelta(seconds=3 * float(settings.worker_heartbeat_seconds) + 10)


async def _workers(session: AsyncSession) -> list[WorkerStatus]:
    now = utcnow()
    rows = await session.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.started_at))
    return [
        WorkerStatus.model_validate(row).model_copy(
            update={"alive": (now - row.last_seen_at) <= _heartbeat_staleness() and not row.stopping}
        )
        for row in rows
    ]


async def _indices() -> list[IndexStatus]:
    from app.search import opensearch

    out: list[IndexStatus] = []
    kinds: tuple[opensearch.IndexKind, ...] = ("chunks", "memory")
    for kind in kinds:
        name = opensearch.index_name(kind)
        try:
            out.append(IndexStatus(kind=kind, name=name, documents=await opensearch.count(kind)))
        except Exception as exc:
            out.append(IndexStatus(kind=kind, name=name, error=str(exc)[:300] or type(exc).__name__))
    return out


def _dependency_out(dep: DependencyStatus) -> DependencyOut:
    return DependencyOut.model_validate(dep.as_dict())


# --- Routes -----------------------------------------------------------------------------------------------


@router.get("/status", response_model=OpsStatus, summary="État d'exploitation de la plateforme")
async def status(admin: AdminUser, session: SessionDep) -> OpsStatus:
    stats = await queue_stats(session)
    workers = await _workers(session)
    tasks = [
        ScheduledTaskOut.model_validate(task)
        for task in await session.scalars(select(ScheduledTask).order_by(ScheduledTask.name))
    ]
    dependencies = await check_core_dependencies()
    indices = await _indices()
    required_ok = all(dep.ok for dep in dependencies if dep.required)
    workers_ok = any(w.alive for w in workers)
    return OpsStatus(
        status="ok" if required_ok and workers_ok else "degraded",
        generated_at=utcnow(),
        version=settings.app_version,
        queue=QueueStatus(
            totals={s: stats.total(s) for s in stats.by_status},
            by_status=stats.by_status,
            oldest_queued_age_seconds=stats.oldest_queued_age_seconds,
            dead_letter=stats.total(JobStatus.dead),
        ),
        workers=workers,
        dependencies=[_dependency_out(d) for d in dependencies],
        indices=indices,
        scheduled_tasks=tasks,
    )


@router.get(
    "/jobs/dead-letter",
    response_model=Page[DeadLetterJob],
    summary="Jobs en file morte (tentatives épuisées ou poison pill)",
)
async def dead_letter(
    admin: AdminUser,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    project: str | None = Query(default=None, description="Slug du projet"),
    kind: JobKind | None = Query(default=None),
) -> Page[DeadLetterJob]:
    conditions: list[Any] = [IngestionJob.status == JobStatus.dead]
    if project is not None:
        project_id = await session.scalar(select(Project.id).where(Project.slug == project))
        if project_id is None:
            raise not_found("Projet introuvable")
        conditions.append(IngestionJob.project_id == project_id)
    if kind is not None:
        conditions.append(IngestionJob.kind == kind)
    total = int(await session.scalar(select(func.count()).select_from(IngestionJob).where(*conditions)) or 0)
    rows = await session.execute(
        select(IngestionJob, Project.slug, Project.name, Document.title, Document.classification)
        .outerjoin(Project, Project.id == IngestionJob.project_id)
        .outerjoin(Document, Document.id == IngestionJob.document_id)
        .where(*conditions)
        .order_by(IngestionJob.finished_at.desc().nulls_last(), IngestionJob.id)
        .offset(params.offset)
        .limit(params.limit)
    )
    items: list[DeadLetterJob] = []
    for job, slug, name, title, classification in rows.tuples():
        update: dict[str, Any] = {"project_slug": slug, "project_name": name, "document_title": title}
        if classification is not None and int(classification) > int(admin.clearance):
            update.update(document_title=RESTRICTED_TITLE, steps=[])
            if job.error:
                update["error"] = RESTRICTED_ERROR
        items.append(DeadLetterJob.model_validate(job).model_copy(update=update))
    return make_page(items, total, params)
