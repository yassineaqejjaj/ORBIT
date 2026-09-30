"""Postgres job queue (``ingestion_jobs``) with ``SELECT … FOR UPDATE SKIP LOCKED``.

Lifecycle::

    queued ──claim──▶ running ──▶ succeeded
       ▲                 │ ├──▶ failed      (PermanentJobError: retrying cannot help)
       │   retry/backoff │ ├──▶ dead        (retries exhausted, or poison pill: the worker died
       └─────────────────┘ │                 POISON_PILL_CRASHES times while running the job)
                           └──▶ cancelled   (POST …/jobs/{id}/cancel)

``failed``, ``dead`` and ``cancelled`` are terminal; :func:`retry_job` puts them back in the queue
with a fresh attempt budget (operator action).

Robustness rules:

* **Fair claim** — :func:`claim_next_job` only considers the head of each project's queue and prefers
  the project with the fewest running jobs, so a bulk import in one project cannot starve the others;
  within a project, higher ``priority`` then older ``run_after`` wins.
* **Lock heartbeat** — the worker refreshes ``locked_at`` of the jobs it runs (:func:`refresh_locks`);
  :func:`reap_stale_jobs` treats a ``running`` job whose lock was not refreshed for the stale threshold
  as a crash: it is re-queued with backoff, or moved to ``dead`` once it looks like a poison pill or has
  no attempt left. Crashes therefore consume attempts, and a crashing job is never re-claimed forever.
* **Cancellation** — a queued (or terminal-failed) job is cancelled at once; a running job gets
  ``cancel_requested_at`` and the worker stops it at its next lock heartbeat.

Transaction rules:

* :func:`enqueue_job`, :func:`mark_succeeded`, :func:`mark_failed`, :func:`mark_cancelled`,
  :func:`requeue_without_attempt`, :func:`retry_job`, :func:`cancel_job` and :func:`append_step` only
  flush — the caller commits (an enqueue is atomic with the document it concerns);
* :func:`claim_next_job`, :func:`refresh_locks` and :func:`reap_stale_jobs` commit themselves so row
  locks are held only for the duration of the statement.

Handlers raise :class:`PermanentJobError` for failures that must not be retried (unsupported file,
corrupt content…); any other exception is retried.
"""

from __future__ import annotations

import random
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import DocumentStatus, JobKind, JobStatus, JobStepStatus
from app.models import Document, IngestionJob
from app.observability.metrics import record_ingestion_job

BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 600.0
MAX_ERROR_LENGTH = 4000
MAX_DETAIL_LENGTH = 1000

#: A job found running with an expired lock this many times is a poison pill (``dead``).
POISON_PILL_CRASHES = 2
#: Number of per-project queue heads examined by one claim (the first lockable one wins).
CLAIM_CANDIDATES = 16

PRIORITY_INTERACTIVE = 10
PRIORITY_DEFAULT = 0
PRIORITY_BULK = -10

ACTIVE_STATUSES: tuple[JobStatus, ...] = (JobStatus.queued, JobStatus.running)
TERMINAL_STATUSES: tuple[JobStatus, ...] = (
    JobStatus.succeeded,
    JobStatus.failed,
    JobStatus.dead,
    JobStatus.cancelled,
)
RETRYABLE_STATUSES: tuple[JobStatus, ...] = (JobStatus.failed, JobStatus.dead, JobStatus.cancelled)
CANCELLABLE_STATUSES: tuple[JobStatus, ...] = (
    JobStatus.queued,
    JobStatus.running,
    JobStatus.failed,
    JobStatus.dead,
)

CRASH_REQUEUED_MESSAGE = "Traitement interrompu (worker arrêté) — relancé automatiquement"


class JobError(Exception):
    """Base class for job failures raised by pipeline handlers."""


class PermanentJobError(JobError):
    """Failure that retrying cannot fix: the job is marked ``failed`` immediately."""


class RetryableJobError(JobError):
    """Transient failure (dependency unavailable…): retried with backoff."""


class JobStateError(Exception):
    """Operator action not allowed in the job's current status (message in French, HTTP 409)."""


def backoff_delay(attempt: int, *, jitter: bool = True) -> float:
    """Seconds to wait before retry number ``attempt`` (1-based): 5 s, 10 s, 20 s … capped at 10 min."""
    delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1)))
    if jitter:
        delay *= random.uniform(0.85, 1.15)
    return delay


def current_traceparent() -> str | None:
    """W3C ``traceparent`` of the active span (``None`` without an active, sampled-or-not trace)."""
    try:
        from opentelemetry.propagate import inject
    except ImportError:  # pragma: no cover - opentelemetry is a hard dependency
        return None
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier.get("traceparent")


async def enqueue_job(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    kind: JobKind | str,
    document_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    run_after: datetime | None = None,
    *,
    max_attempts: int = 3,
    priority: int = PRIORITY_DEFAULT,
) -> IngestionJob:
    """Add a ``queued`` job to the session (flushed so ``job.id`` is available; caller commits).

    ``project_id`` is ``None`` only for platform-wide jobs (global reindex). The enqueuing request's
    trace context is stored so the worker span can be linked to it.
    """
    job = IngestionJob(
        project_id=project_id,
        document_id=document_id,
        kind=JobKind(kind),
        status=JobStatus.queued,
        priority=int(priority),
        attempts=0,
        max_attempts=max(1, max_attempts),
        crash_count=0,
        payload=dict(payload or {}),
        steps=[],
        run_after=run_after or utcnow(),
        trace_parent=current_traceparent(),
    )
    session.add(job)
    await session.flush()
    return job


def _runnable(now: datetime, kinds: Sequence[JobKind | str] | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        IngestionJob.status == JobStatus.queued,
        IngestionJob.run_after <= now,
    ]
    if kinds:
        conditions.append(IngestionJob.kind.in_([JobKind(k) for k in kinds]))
    return conditions


async def _fair_candidates(
    session: AsyncSession, now: datetime, kinds: Sequence[JobKind | str] | None
) -> list[uuid.UUID]:
    """Head job of each project's runnable queue, least-busy project first (no row lock taken)."""
    heads = (
        select(
            IngestionJob.id,
            IngestionJob.project_id,
            IngestionJob.priority,
            IngestionJob.run_after,
            IngestionJob.created_at,
        )
        .where(*_runnable(now, kinds))
        .distinct(IngestionJob.project_id)
        .order_by(
            IngestionJob.project_id,
            IngestionJob.priority.desc(),
            IngestionJob.run_after,
            IngestionJob.created_at,
        )
        .subquery("heads")
    )
    running = (
        select(IngestionJob.project_id, func.count().label("n"))
        .where(IngestionJob.status == JobStatus.running)
        .group_by(IngestionJob.project_id)
        .subquery("running")
    )
    stmt = (
        select(heads.c.id)
        .outerjoin(running, running.c.project_id.is_not_distinct_from(heads.c.project_id))
        .order_by(
            func.coalesce(running.c.n, 0),
            heads.c.priority.desc(),
            heads.c.run_after,
            heads.c.created_at,
        )
        .limit(CLAIM_CANDIDATES)
    )
    return list(await session.scalars(stmt))


async def claim_next_job(
    session: AsyncSession,
    worker_id: str,
    kinds: Sequence[JobKind | str] | None = None,
) -> IngestionJob | None:
    """Atomically claim the next runnable job (commits). Returns ``None`` when the queue is empty.

    Candidates are the heads of each project's queue ordered by the project's current number of
    running jobs, then priority and age; the first one that can be locked (``SKIP LOCKED``) is claimed.
    When every head is being claimed concurrently, the oldest lockable runnable job is taken instead
    so the claim always makes progress.

    The claimed job is ``running``, ``attempts`` is incremented, ``locked_by/locked_at/started_at``
    are set and ``steps`` are reset for the new attempt.
    """
    now = utcnow()
    job: IngestionJob | None = None
    for candidate_id in await _fair_candidates(session, now, kinds):
        job = await session.scalar(
            select(IngestionJob)
            .where(IngestionJob.id == candidate_id, *_runnable(now, kinds))
            .with_for_update(skip_locked=True)
        )
        if job is not None:
            break
    if job is None:
        job = await session.scalar(
            select(IngestionJob)
            .where(*_runnable(now, kinds))
            .order_by(IngestionJob.priority.desc(), IngestionJob.run_after, IngestionJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
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
    await session.commit()
    return job


def _release(job: IngestionJob) -> None:
    job.locked_by = None
    job.locked_at = None


async def _settle_document(
    session: AsyncSession, job: IngestionJob, status: DocumentStatus, reason: str | None
) -> None:
    """Align the document of an ``ingest`` job that ends (or restarts) outside the pipeline.

    Terminal outcomes decided by the queue itself (crash dead letter, cancellation) mark a document
    still ``pending``/``processing`` as ``failed``; a retry puts a ``failed`` document back to
    ``pending``. Other documents (indexed, forgotten) are left untouched.
    """
    if job.kind != JobKind.ingest or job.document_id is None:
        return
    document = await session.get(Document, job.document_id)
    if document is None:
        return
    expected = (
        (DocumentStatus.failed,)
        if status == DocumentStatus.pending
        else (DocumentStatus.pending, DocumentStatus.processing)
    )
    if document.status in expected:
        document.status = status
        document.status_reason = reason[:1000] if reason else None


async def mark_succeeded(session: AsyncSession, job: IngestionJob) -> None:
    job.status = JobStatus.succeeded
    job.finished_at = utcnow()
    job.error = None
    job.cancel_requested_at = None
    _release(job)
    await session.flush()
    record_ingestion_job("succeeded")


async def mark_failed(
    session: AsyncSession,
    job: IngestionJob,
    error: str | BaseException,
    *,
    retryable: bool = True,
) -> bool:
    """Record a failed attempt. Returns ``True`` when the job was re-queued for a retry.

    A retryable failure with no attempt left moves the job to the dead letter (``dead``); a
    permanent failure ends it as ``failed``.
    """
    job.error = _error_message(error)[:MAX_ERROR_LENGTH]
    _release(job)
    if retryable and job.attempts < job.max_attempts:
        job.status = JobStatus.queued
        job.run_after = utcnow() + timedelta(seconds=backoff_delay(job.attempts))
        await session.flush()
        record_ingestion_job("retried")
        return True
    job.status = JobStatus.dead if retryable else JobStatus.failed
    job.finished_at = utcnow()
    await session.flush()
    record_ingestion_job(job.status.value)
    return False


async def mark_cancelled(session: AsyncSession, job: IngestionJob, reason: str | None = None) -> None:
    """End ``job`` as ``cancelled`` (worker side, after honouring a cancel request)."""
    job.status = JobStatus.cancelled
    job.finished_at = utcnow()
    job.error = (reason or "Traitement annulé")[:MAX_ERROR_LENGTH]
    _release(job)
    await _settle_document(session, job, DocumentStatus.failed, "Ingestion annulée — relancez le traitement")
    await session.flush()
    record_ingestion_job("cancelled")


async def requeue_without_attempt(
    session: AsyncSession,
    job: IngestionJob,
    *,
    delay_seconds: float = 0.0,
    error: str | None = None,
) -> None:
    """Put a running job back in the queue without consuming an attempt.

    Used when the attempt did not really run: graceful worker shutdown, or a per-project lock that
    was busy (``lock_timeout``).
    """
    job.status = JobStatus.queued
    job.attempts = max(0, job.attempts - 1)
    job.run_after = utcnow() + timedelta(seconds=max(0.0, delay_seconds))
    if error is not None:
        job.error = error[:MAX_ERROR_LENGTH]
    _release(job)
    await session.flush()
    record_ingestion_job("requeued")


def _error_message(error: str | BaseException) -> str:
    if isinstance(error, BaseException):
        text = str(error).strip()
        return text or type(error).__name__
    return str(error)


# --- Operator actions (API / CLI) ----------------------------------------------------------------------


async def retry_job(session: AsyncSession, job: IngestionJob) -> IngestionJob:
    """Re-queue a ``failed`` / ``dead`` / ``cancelled`` job with a fresh attempt budget (flushes).

    Raises :class:`JobStateError` when the job is not in a retryable status or when another active
    job already processes the same document with the same kind.
    """
    if job.status not in RETRYABLE_STATUSES:
        raise JobStateError(
            f"Seul un job en échec, en file morte ou annulé peut être relancé (statut : {job.status})."
        )
    if job.document_id is not None:
        duplicate = await session.scalar(
            select(IngestionJob.id).where(
                IngestionJob.document_id == job.document_id,
                IngestionJob.kind == job.kind,
                IngestionJob.status.in_(ACTIVE_STATUSES),
                IngestionJob.id != job.id,
            )
        )
        if duplicate is not None:
            raise JobStateError("Un traitement du même type est déjà en cours pour ce document.")
    job.status = JobStatus.queued
    job.attempts = 0
    job.crash_count = 0
    job.error = None
    job.run_after = utcnow()
    job.started_at = None
    job.finished_at = None
    job.cancel_requested_at = None
    _release(job)
    await _settle_document(session, job, DocumentStatus.pending, None)
    await session.flush()
    record_ingestion_job("requeued")
    return job


async def cancel_job(session: AsyncSession, job: IngestionJob, *, reason: str | None = None) -> IngestionJob:
    """Cancel ``job`` (flushes).

    Queued and terminal-failed jobs become ``cancelled`` immediately; a running job gets
    ``cancel_requested_at`` and is stopped by its worker at the next lock heartbeat (or by the stale
    reaper if that worker is gone). Raises :class:`JobStateError` for succeeded/cancelled jobs.
    """
    if job.status not in CANCELLABLE_STATUSES:
        raise JobStateError(f"Ce job ne peut pas être annulé (statut : {job.status}).")
    if job.status == JobStatus.running:
        if job.cancel_requested_at is None:
            job.cancel_requested_at = utcnow()
        await session.flush()
        return job
    await mark_cancelled(session, job, reason)
    return job


# --- Worker side: lock heartbeat and crash recovery -----------------------------------------------------


@dataclass(slots=True, frozen=True)
class LockRefresh:
    """Running job of a worker whose lock was just refreshed."""

    job_id: uuid.UUID
    cancel_requested: bool


async def refresh_locks(session: AsyncSession, worker_id: str) -> list[LockRefresh]:
    """Refresh ``locked_at`` of every job ``worker_id`` runs (commits) and report cancel requests."""
    result = await session.execute(
        update(IngestionJob)
        .where(IngestionJob.locked_by == worker_id, IngestionJob.status == JobStatus.running)
        .values(locked_at=func.now())
        .returning(IngestionJob.id, IngestionJob.cancel_requested_at)
    )
    rows = [
        LockRefresh(job_id=job_id, cancel_requested=requested is not None) for job_id, requested in result
    ]
    await session.commit()
    return rows


@dataclass(slots=True)
class ReapResult:
    """Outcome of :func:`reap_stale_jobs` (job ids per decision)."""

    requeued: list[uuid.UUID] = field(default_factory=list)
    dead: list[uuid.UUID] = field(default_factory=list)
    cancelled: list[uuid.UUID] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.requeued) + len(self.dead) + len(self.cancelled)


async def reap_stale_jobs(session: AsyncSession, older_than_seconds: float) -> ReapResult:
    """Recover ``running`` jobs whose lock was not refreshed for ``older_than_seconds`` (commits).

    The owning worker is presumed dead (crash, OOM kill): ``crash_count`` is incremented and the
    job is re-queued with backoff — or moved to ``dead`` when it crashed ``POISON_PILL_CRASHES``
    times or has no attempt left, or ``cancelled`` when a cancel was requested.
    """
    now = utcnow()
    threshold = now - timedelta(seconds=older_than_seconds)
    stale = list(
        await session.scalars(
            select(IngestionJob)
            .where(
                IngestionJob.status == JobStatus.running,
                or_(IngestionJob.locked_at < threshold, IngestionJob.locked_at.is_(None)),
            )
            .with_for_update(skip_locked=True)
        )
    )
    result = ReapResult()
    for job in stale:
        job.crash_count = job.crash_count + 1
        _release(job)
        if job.cancel_requested_at is not None:
            job.status = JobStatus.cancelled
            job.finished_at = now
            job.error = "Traitement annulé (worker arrêté pendant l'annulation)"
            await _settle_document(
                session, job, DocumentStatus.failed, "Ingestion annulée — relancez le traitement"
            )
            result.cancelled.append(job.id)
            record_ingestion_job("cancelled")
        elif job.crash_count >= POISON_PILL_CRASHES or job.attempts >= job.max_attempts:
            job.status = JobStatus.dead
            job.finished_at = now
            job.error = (
                f"Job abandonné : le worker s'est arrêté {job.crash_count} fois pendant son traitement "
                f"(tentative {job.attempts}/{job.max_attempts}). Relancez-le après correction."
            )
            await _settle_document(session, job, DocumentStatus.failed, job.error)
            result.dead.append(job.id)
            record_ingestion_job("dead")
        else:
            job.status = JobStatus.queued
            job.run_after = now + timedelta(seconds=backoff_delay(job.attempts))
            job.error = CRASH_REQUEUED_MESSAGE
            result.requeued.append(job.id)
            record_ingestion_job("requeued")
    await session.commit()
    return result


# --- Queue statistics (ops status, backlog gauges) -------------------------------------------------------


@dataclass(slots=True)
class QueueStats:
    #: ``{status: {kind: count}}`` over every job still in the table.
    by_status: dict[str, dict[str, int]]
    #: Age in seconds of the oldest runnable queued job, by kind.
    oldest_queued_age_seconds: dict[str, float]

    def total(self, status: JobStatus | str) -> int:
        return sum(self.by_status.get(str(status), {}).values())


async def queue_stats(session: AsyncSession) -> QueueStats:
    by_status: dict[str, dict[str, int]] = {}
    rows = await session.execute(
        select(IngestionJob.status, IngestionJob.kind, func.count()).group_by(
            IngestionJob.status, IngestionJob.kind
        )
    )
    for status, kind, count in rows.tuples():
        by_status.setdefault(str(status), {})[str(kind)] = int(count)
    now = utcnow()
    oldest: dict[str, float] = {}
    oldest_rows = await session.execute(
        select(IngestionJob.kind, func.min(IngestionJob.run_after))
        .where(IngestionJob.status == JobStatus.queued, IngestionJob.run_after <= now)
        .group_by(IngestionJob.kind)
    )
    for kind, run_after in oldest_rows.tuples():
        if run_after is not None:
            oldest[str(kind)] = max(0.0, (now - run_after).total_seconds())
    return QueueStats(by_status=by_status, oldest_queued_age_seconds=oldest)


# --- Pipeline steps ---------------------------------------------------------------------------------------


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
