"""Postgres job queue (``ingestion_jobs``) with ``SELECT … FOR UPDATE SKIP LOCKED``.

Lifecycle: ``queued`` → (claimed) ``running`` → ``succeeded`` | ``failed``; a failed attempt is
re-queued with exponential backoff until ``max_attempts`` is reached.

Transaction rules:

* :func:`enqueue_job`, :func:`mark_succeeded`, :func:`mark_failed` and :func:`append_step` only
  flush — the caller commits (an enqueue is atomic with the document it concerns);
* :func:`claim_next_job` and :func:`requeue_stale_jobs` commit themselves so the row lock is held
  only for the duration of the claim.

Handlers raise :class:`PermanentJobError` for failures that must not be retried (unsupported file,
corrupt content…); any other exception is retried.
"""

from __future__ import annotations

import random
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import JobKind, JobStatus, JobStepStatus
from app.models import IngestionJob
from app.features.live import hooks as live_hooks
from app.observability.metrics import record_ingestion_job

BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 600.0
MAX_ERROR_LENGTH = 4000
MAX_DETAIL_LENGTH = 1000


class JobError(Exception):
    """Base class for job failures raised by pipeline handlers."""


class PermanentJobError(JobError):
    """Failure that retrying cannot fix: the job is marked ``failed`` immediately."""


class RetryableJobError(JobError):
    """Transient failure (dependency unavailable…): retried with backoff."""


def backoff_delay(attempt: int, *, jitter: bool = True) -> float:
    """Seconds to wait before retry number ``attempt`` (1-based): 5 s, 10 s, 20 s … capped at 10 min."""
    delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1)))
    if jitter:
        delay *= random.uniform(0.85, 1.15)
    return delay


async def enqueue_job(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: JobKind | str,
    document_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    run_after: datetime | None = None,
    *,
    max_attempts: int = 3,
) -> IngestionJob:
    """Add a ``queued`` job to the session (flushed so ``job.id`` is available; caller commits)."""
    job = IngestionJob(
        project_id=project_id,
        document_id=document_id,
        kind=JobKind(kind),
        status=JobStatus.queued,
        attempts=0,
        max_attempts=max(1, max_attempts),
        payload=dict(payload or {}),
        steps=[],
        run_after=run_after or utcnow(),
    )
    session.add(job)
    await session.flush()
    return job


async def claim_next_job(
    session: AsyncSession,
    worker_id: str,
    kinds: Sequence[JobKind | str] | None = None,
) -> IngestionJob | None:
    """Atomically claim the oldest runnable job (commits). Returns ``None`` when the queue is empty.

    The claimed job is ``running``, ``attempts`` is incremented, ``locked_by/locked_at/started_at``
    are set and ``steps``/``error`` are reset for the new attempt.
    """
    now = utcnow()
    stmt = (
        select(IngestionJob)
        .where(IngestionJob.status == JobStatus.queued, IngestionJob.run_after <= now)
        .order_by(IngestionJob.run_after, IngestionJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if kinds:
        stmt = stmt.where(IngestionJob.kind.in_([JobKind(k) for k in kinds]))
    job = await session.scalar(stmt)
    if job is None:
        await session.rollback()
        return None
    job.status = JobStatus.running
    job.attempts = job.attempts + 1
    job.locked_by = worker_id
    job.locked_at = now
    job.started_at = now
    job.finished_at = None
    job.steps = []
    live_hooks.job_updated(session, job)
    await session.commit()
    return job


async def mark_succeeded(session: AsyncSession, job: IngestionJob) -> None:
    now = utcnow()
    job.status = JobStatus.succeeded
    job.finished_at = now
    job.locked_by = None
    job.locked_at = None
    job.error = None
    await session.flush()
    live_hooks.job_updated(session, job)
    record_ingestion_job("succeeded")


async def mark_failed(
    session: AsyncSession,
    job: IngestionJob,
    error: str | BaseException,
    *,
    retryable: bool = True,
) -> bool:
    """Record a failed attempt. Returns ``True`` when the job was re-queued for a retry."""
    message = _error_message(error)
    job.error = message[:MAX_ERROR_LENGTH]
    job.locked_by = None
    job.locked_at = None
    if retryable and job.attempts < job.max_attempts:
        job.status = JobStatus.queued
        job.run_after = utcnow() + timedelta(seconds=backoff_delay(job.attempts))
        await session.flush()
        live_hooks.job_updated(session, job)
        record_ingestion_job("retried")
        return True
    job.status = JobStatus.failed
    job.finished_at = utcnow()
    await session.flush()
    live_hooks.job_updated(session, job)
    record_ingestion_job("failed")
    return False


def _error_message(error: str | BaseException) -> str:
    if isinstance(error, BaseException):
        text = str(error).strip()
        return text or type(error).__name__
    return str(error)


async def append_step(
    session: AsyncSession,
    job: IngestionJob,
    name: str,
    status: JobStepStatus | str,
    duration_ms: float,
    detail: str | None = None,
    *,
    started_at: datetime | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """Append a pipeline step to ``job.steps`` (shown live on the Sources screen).

    ``commit=True`` commits immediately so the UI sees progress while the job runs (only use it when
    the pipeline's pending changes may be committed at that point).
    """
    step = {
        "name": str(name),
        "status": JobStepStatus(status).value,
        "started_at": (started_at or utcnow()).isoformat(),
        "duration_ms": round(float(duration_ms), 1),
        "detail": (detail[:MAX_DETAIL_LENGTH] if detail else None),
    }
    job.steps = [*(job.steps or []), step]  # reassign: JSONB change detection
    await session.flush()
    if commit:
        await session.commit()
    return step


@dataclass(slots=True)
class StepRecorder:
    """Handle yielded by :func:`track_step`; set ``detail`` or call :meth:`skip`."""

    detail: str | None = None
    skipped: bool = False

    def skip(self, detail: str | None = None) -> None:
        self.skipped = True
        if detail:
            self.detail = detail


@asynccontextmanager
async def track_step(
    session: AsyncSession, job: IngestionJob, name: str, *, commit: bool = False
) -> AsyncIterator[StepRecorder]:
    """Time a pipeline step and append it as ``ok`` / ``skipped`` / ``failed`` (then re-raise).

    Example::

        async with track_step(session, job, "chunk") as step:
            chunks = chunker.split(text)
            step.detail = f"{len(chunks)} fragments"
    """
    recorder = StepRecorder()
    started_at = utcnow()
    started = time.perf_counter()
    try:
        yield recorder
    except BaseException as exc:
        elapsed = (time.perf_counter() - started) * 1000
        await append_step(
            session,
            job,
            name,
            JobStepStatus.failed,
            elapsed,
            _error_message(exc),
            started_at=started_at,
            commit=False,
        )
        raise
    elapsed = (time.perf_counter() - started) * 1000
    status = JobStepStatus.skipped if recorder.skipped else JobStepStatus.ok
    await append_step(
        session, job, name, status, elapsed, recorder.detail, started_at=started_at, commit=commit
    )


async def requeue_stale_jobs(session: AsyncSession, older_than_seconds: float) -> int:
    """Re-queue ``running`` jobs whose lock is older than the threshold (crashed worker). Commits."""
    threshold = utcnow() - timedelta(seconds=older_than_seconds)
    result = await session.execute(
        update(IngestionJob)
        .where(IngestionJob.status == JobStatus.running, IngestionJob.locked_at < threshold)
        .values(
            status=JobStatus.queued,
            locked_by=None,
            locked_at=None,
            run_after=utcnow(),
            error="Traitement interrompu (worker arrêté) — relancé automatiquement",
        )
        .returning(IngestionJob.id)
    )
    count = len(result.all())
    await session.commit()
    return count
