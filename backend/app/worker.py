"""ORBIT worker: processes the Postgres job queue (``python -m app.worker``).

* ``ORBIT_WORKER_CONCURRENCY`` slots claim jobs fairly across projects (``app.ingestion.queue``) and
  run ``app.ingestion.pipeline.run_job`` (one DB session per job, job timeout enforced, every job
  transaction bounded by ``lock_timeout``: a busy per-project lock re-queues the job without consuming
  an attempt instead of blocking a slot);
* failures are retried with exponential backoff, then dead-lettered (``dead``);
* **lock heartbeat**: every heartbeat interval the worker refreshes ``locked_at`` of its running jobs,
  stops jobs whose cancellation was requested and upserts its ``worker_heartbeats`` row;
* **stale reaper**: ``running`` jobs whose lock was not refreshed for ``ORBIT_WORKER_STALE_LOCK_SECONDS``
  (crashed worker) are re-queued, or dead-lettered as poison pills;
* **cluster-wide singleton tasks** (``pg_try_advisory_lock`` + ``scheduled_tasks`` due check): memory
  maintenance, daily retention purge (``app.compliance.retention.run_retention`` when present),
  housekeeping of worker heartbeats — each runs once per interval across all replicas;
* internal HTTP endpoint on ``ORBIT_WORKER_METRICS_PORT``: ``/healthz`` (liveness) and ``/metrics``;
* SIGTERM/SIGINT: stop claiming, let in-flight jobs finish within
  ``ORBIT_WORKER_SHUTDOWN_GRACE_SECONDS``, then cancel them (re-queued without consuming an attempt).

Cancellation is cooperative: work already running in a thread (``asyncio.to_thread``) finishes in the
background but its result is discarded (the transaction is rolled back).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
import signal
import socket
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, event, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.config import settings
from app.db import dispose_engine, get_engine, get_sessionmaker, utcnow
from app.enums import JobStatus
from app.ingestion import pipeline
from app.ingestion.queue import (
    PermanentJobError,
    backoff_delay,
    claim_next_job,
    mark_cancelled,
    mark_failed,
    mark_succeeded,
    queue_stats,
    reap_stale_jobs,
    refresh_locks,
    requeue_without_attempt,
)
from app.models import IngestionJob
from app.models.job import ScheduledTask, WorkerHeartbeat
from app.observability.context import bind_log_context
from app.observability.internal_server import InternalServer
from app.observability.logging_setup import setup_logging
from app.observability.metrics import (
    JOB_DURATION_SECONDS,
    QUEUE_JOBS,
    QUEUE_OLDEST_AGE_SECONDS,
    SCHEDULED_TASK_RUNS_TOTAL,
    WORKER_INFLIGHT,
    WORKER_LAST_LOOP_TIMESTAMP,
)
from app.observability.runtime_config import opt
from app.observability.tracing import get_tracer, setup_tracing, shutdown_tracing

logger = logging.getLogger("orbit.worker")

ERROR_BACKOFF_SECONDS = 5.0
#: Documented default of ``ORBIT_WORKER_STALE_LOCK_SECONDS`` (lock heartbeat keeps live jobs fresh).
DEFAULT_STALE_LOCK_SECONDS = 600.0
#: Documented default of ``ORBIT_WORKER_LOCK_TIMEOUT_MS`` (Postgres ``lock_timeout`` of job transactions).
DEFAULT_LOCK_TIMEOUT_MS = 30_000
#: A job re-queued this many times because its project lock was busy then counts a normal failure.
MAX_LOCK_WAITS = 40
LOCK_WAITS_PAYLOAD_KEY = "_lock_waits"
LOCK_BUSY_MESSAGE = "En attente : un autre traitement du projet détient le verrou — relancé automatiquement"
#: Heartbeat rows of workers unseen for this long are removed by the housekeeping task.
HEARTBEAT_RETENTION = timedelta(days=1)
#: SQLSTATE of ``lock_not_available`` (raised when ``lock_timeout`` expires).
LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"

TaskFn = Callable[[AsyncSession], Awaitable[dict[str, Any] | None]]


class TaskUnavailable(Exception):
    """A scheduled task's implementation is not installed on this instance (recorded as ``skipped``)."""


@dataclass
class WorkerStats:
    started_at: float = field(default_factory=time.monotonic)
    succeeded: int = 0
    failed: int = 0
    dead: int = 0
    retried: int = 0
    requeued: int = 0
    cancelled: int = 0
    in_flight: int = 0


@dataclass(frozen=True, slots=True)
class ScheduledSpec:
    """Cluster-wide singleton task run at most once per ``interval_seconds``."""

    name: str
    interval_seconds: float
    fn: TaskFn


def is_lock_timeout(exc: BaseException) -> bool:
    """``True`` when ``exc`` (or its cause/context chain) is a Postgres ``lock_not_available`` error."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code == LOCK_NOT_AVAILABLE_SQLSTATE:
            return True
        orig = getattr(current, "orig", None)
        stack.extend(
            [
                orig if isinstance(orig, BaseException) else None,
                current.__cause__,
                current.__context__,
            ]
        )
    return False


def _jsonable(summary: Any) -> dict[str, Any]:
    if summary is None:
        return {}
    if isinstance(summary, dict):
        return {
            str(k): v if isinstance(v, (int, float, str, bool, type(None))) else str(v)
            for k, v in summary.items()
        }
    if dataclasses.is_dataclass(summary) and not isinstance(summary, type):
        return _jsonable(dataclasses.asdict(summary))
    if hasattr(summary, "model_dump"):
        return _jsonable(summary.model_dump(mode="json"))
    return {"result": str(summary)}


# --- Scheduled task implementations ------------------------------------------------------------------------


async def memory_maintenance_task(session: AsyncSession) -> dict[str, Any] | None:
    from app.memory import lifecycle

    try:
        return await lifecycle.run_periodic_maintenance(session)
    except NotImplementedError as exc:
        raise TaskUnavailable("Maintenance mémoire non disponible") from exc


async def retention_task(session: AsyncSession) -> dict[str, Any] | None:
    """Daily RGPD retention purge, implemented by the compliance module when installed."""
    try:
        from app.compliance.retention import run_retention
    except ImportError as exc:
        raise TaskUnavailable("Module de rétention absent (app.compliance.retention)") from exc
    return _jsonable(await run_retention(session))


async def housekeeping_task(session: AsyncSession) -> dict[str, Any] | None:
    result = await session.execute(
        delete(WorkerHeartbeat)
        .where(WorkerHeartbeat.last_seen_at < utcnow() - HEARTBEAT_RETENTION)
        .returning(WorkerHeartbeat.worker_id)
    )
    return {"heartbeats_removed": len(result.all())}


def default_schedule() -> list[ScheduledSpec]:
    return [
        ScheduledSpec(
            "memory_maintenance", settings.worker_maintenance_interval_seconds, memory_maintenance_task
        ),
        ScheduledSpec("retention", float(opt("retention_interval_seconds", 86_400.0)), retention_task),
        ScheduledSpec("housekeeping", 3_600.0, housekeeping_task),
    ]


def _task_lock_key(name: str) -> Any:
    return func.hashtextextended(f"orbit:scheduled-task:{name}", 0)


async def run_singleton_task(spec: ScheduledSpec, holder: str, *, force: bool = False) -> str:
    """Run ``spec`` if it is due and no other process runs it. Returns the outcome.

    Outcomes: ``ok`` | ``failed`` | ``skipped`` (implementation unavailable) | ``not_due`` |
    ``locked`` (another replica holds the task lock). The session-level advisory lock is held on a
    dedicated connection for the duration of the run, so a crashed holder releases it automatically.
    """
    engine = get_engine()
    async with engine.connect() as lock_conn:
        acquired = bool(await lock_conn.scalar(select(func.pg_try_advisory_lock(_task_lock_key(spec.name)))))
        await lock_conn.commit()
        if not acquired:
            return "locked"
        try:
            return await _run_locked_task(spec, holder, force=force)
        finally:
            try:
                await lock_conn.scalar(select(func.pg_advisory_unlock(_task_lock_key(spec.name))))
                await lock_conn.commit()
            except Exception:  # never return a connection that may still hold the lock to the pool
                await lock_conn.invalidate()


async def _run_locked_task(spec: ScheduledSpec, holder: str, *, force: bool) -> str:
    sessionmaker = get_sessionmaker()
    now = utcnow()
    async with sessionmaker() as session:
        row = await session.get(ScheduledTask, spec.name)
        if (
            not force
            and row is not None
            and row.last_started_at is not None
            and (now - row.last_started_at).total_seconds() < spec.interval_seconds * 0.95
        ):
            return "not_due"
        if row is None:
            row = ScheduledTask(name=spec.name)
            session.add(row)
        row.last_started_at = now
        row.last_status = "running"
        row.holder = holder
        await session.commit()

    status, error, summary = "ok", None, {}
    async with sessionmaker() as session:
        try:
            summary = _jsonable(await spec.fn(session))
            await session.commit()
        except TaskUnavailable as exc:
            await session.rollback()
            status, error = "skipped", str(exc)
        except Exception as exc:
            await session.rollback()
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
            logger.exception("Scheduled task %s failed", spec.name)

    async with sessionmaker() as session:
        row = await session.get(ScheduledTask, spec.name)
        if row is not None:
            row.last_finished_at = utcnow()
            row.last_status = status
            row.last_error = error
            row.last_summary = summary
            await session.commit()
    SCHEDULED_TASK_RUNS_TOTAL.labels(task=spec.name, status=status).inc()
    if status == "ok" and summary:
        logger.info("Scheduled task %s: %s", spec.name, summary)
    elif status == "skipped":
        logger.info("Scheduled task %s skipped: %s", spec.name, error)
    return status


# --- Worker -------------------------------------------------------------------------------------------------


class Worker:
    def __init__(
        self,
        concurrency: int | None = None,
        worker_id: str | None = None,
        *,
        heartbeat_interval: float | None = None,
        stale_lock_seconds: float | None = None,
        lock_timeout_ms: int | None = None,
        schedule: list[ScheduledSpec] | None = None,
    ) -> None:
        self.concurrency = concurrency or settings.worker_concurrency
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
        self.worker_id = worker_id or f"{self.hostname}:{self.pid}:{uuid.uuid4().hex[:6]}"
        self.stale_lock_seconds = float(
            stale_lock_seconds
            if stale_lock_seconds is not None
            else opt("worker_stale_lock_seconds", DEFAULT_STALE_LOCK_SECONDS)
        )
        self.heartbeat_interval = float(
            heartbeat_interval
            if heartbeat_interval is not None
            else max(1.0, min(settings.worker_heartbeat_seconds, self.stale_lock_seconds / 4))
        )
        self.lock_timeout_ms = int(
            lock_timeout_ms
            if lock_timeout_ms is not None
            else opt("worker_lock_timeout_ms", DEFAULT_LOCK_TIMEOUT_MS)
        )
        self.schedule = default_schedule() if schedule is None else schedule
        self.stop_event = asyncio.Event()
        self.stats = WorkerStats()
        self.started_at: datetime = utcnow()
        self._tracer = get_tracer("orbit.worker")
        self._running: dict[uuid.UUID, asyncio.Task[Any]] = {}
        self._cancel_requested: set[uuid.UUID] = set()
        self._background: list[asyncio.Task[None]] = []
        self._last_heartbeat = time.monotonic()
        self._last_log = 0.0
        self._db_ok = True

    # -- lifecycle -------------------------------------------------------------------------------
    def request_stop(self) -> None:
        if not self.stop_event.is_set():
            logger.info(
                "Shutdown requested: finishing in-flight jobs (grace %.0fs)",
                settings.worker_shutdown_grace_seconds,
            )
            self.stop_event.set()

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stop_event.wait(), timeout=max(0.0, seconds))

    async def run(self) -> None:
        logger.info("Worker %s starting (concurrency=%d)", self.worker_id, self.concurrency)
        await self._prepare_indices()
        slots = [asyncio.create_task(self._slot(i), name=f"slot-{i}") for i in range(self.concurrency)]
        self._background = [
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
            asyncio.create_task(self._reaper_loop(), name="stale-reaper"),
            asyncio.create_task(self._scheduler_loop(), name="scheduler"),
        ]
        await self.stop_event.wait()
        with contextlib.suppress(Exception):
            await self._write_heartbeat()  # advertise ``stopping`` to /ops/status

        # Stop claiming; give running jobs a grace period.
        _done, pending = await asyncio.wait(slots, timeout=settings.worker_shutdown_grace_seconds)
        for task in pending:
            task.cancel()
        for task in self._background:
            task.cancel()
        await asyncio.gather(*pending, *self._background, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self._remove_heartbeat()
        logger.info(
            "Worker %s stopped (succeeded=%d failed=%d dead=%d retried=%d cancelled=%d)",
            self.worker_id,
            self.stats.succeeded,
            self.stats.failed,
            self.stats.dead,
            self.stats.retried,
            self.stats.cancelled,
        )

    async def _prepare_indices(self) -> None:
        from app.search import opensearch

        try:
            await opensearch.ensure_indices()
        except NotImplementedError:
            logger.warning("OpenSearch index setup not implemented yet — skipped")
        except Exception as exc:  # OpenSearch may still be starting: the API also ensures indices
            logger.warning("OpenSearch index setup failed at worker start: %s", exc)

    async def health(self) -> tuple[bool, dict[str, Any]]:
        """Liveness: the event loop answers and the heartbeat loop keeps ticking.

        Dependency outages do not fail liveness (a restart would not fix them); they are reported.
        """
        age = time.monotonic() - self._last_heartbeat
        loops_alive = bool(self._background) and all(not task.done() for task in self._background)
        healthy = loops_alive and age < 3 * self.heartbeat_interval + 10
        return healthy, {
            "worker_id": self.worker_id,
            "in_flight": self.stats.in_flight,
            "last_heartbeat_age_seconds": round(age, 1),
            "database": "ok" if self._db_ok else "down",
            "stopping": self.stop_event.is_set(),
        }

    # -- job slots -----------------------------------------------------------------------------------
    async def _slot(self, index: int) -> None:
        sessionmaker = get_sessionmaker()
        while not self.stop_event.is_set():
            try:
                async with sessionmaker() as session:
                    job = await claim_next_job(session, self.worker_id)
            except Exception:
                logger.exception("Slot %d: unable to claim a job (database unavailable?)", index)
                await self._sleep(ERROR_BACKOFF_SECONDS)
                continue
            if job is None:
                await self._sleep(settings.worker_poll_interval_seconds)
                continue
            await self._process(job.id)

    def _bound_lock_waits(self, session: AsyncSession) -> None:
        """``SET LOCAL lock_timeout`` at the start of every transaction of the job session."""
        if self.lock_timeout_ms <= 0:
            return
        statement = f"SET LOCAL lock_timeout = {int(self.lock_timeout_ms)}"

        @event.listens_for(session.sync_session, "after_begin")
        def _set_lock_timeout(
            _session: Session, _transaction: SessionTransaction, connection: Connection
        ) -> None:
            connection.exec_driver_sql(statement)

    async def _process(self, job_id: uuid.UUID) -> None:
        sessionmaker = get_sessionmaker()
        self.stats.in_flight += 1
        WORKER_INFLIGHT.inc()
        started = time.perf_counter()
        kind = "unknown"
        outcome = "error"
        try:
            async with sessionmaker() as session:
                self._bound_lock_waits(session)
                job = await session.get(IngestionJob, job_id)
                if job is None:
                    return
                kind = str(job.kind)
                label = (
                    f"{job.kind} job={job.id} doc={job.document_id} attempt={job.attempts}/{job.max_attempts}"
                )
                with (
                    bind_log_context(job_id=job.id, project=job.project_id),
                    self._tracer.start_as_current_span(f"job.{job.kind}") as span,
                ):
                    span.set_attribute("orbit.job_id", str(job.id))
                    span.set_attribute("orbit.project_id", str(job.project_id))
                    span.set_attribute("orbit.attempt", job.attempts)
                    logger.info("Running %s", label)
                    runner = asyncio.create_task(
                        asyncio.wait_for(
                            pipeline.run_job(session, job), timeout=settings.worker_job_timeout_seconds
                        ),
                        name=f"job-{job.id}",
                    )
                    self._running[job_id] = runner
                    try:
                        await runner
                    except asyncio.CancelledError:
                        current = asyncio.current_task()
                        if job_id in self._cancel_requested and (
                            current is None or current.cancelling() == 0
                        ):
                            with contextlib.suppress(Exception):
                                await session.rollback()
                            await self._finish_cancelled(job_id)
                            outcome = "cancelled"
                            return
                        raise
                    except Exception as exc:
                        span.record_exception(exc)
                        with contextlib.suppress(Exception):
                            await session.rollback()
                        outcome = await self._fail(job_id, exc)
                        return
                    finally:
                        self._running.pop(job_id, None)
                    await mark_succeeded(session, job)
                    await session.commit()
                    self.stats.succeeded += 1
                    outcome = "succeeded"
                    logger.info("Succeeded %s in %.0f ms", label, (time.perf_counter() - started) * 1000)
        except asyncio.CancelledError:
            logger.warning("Job %s interrupted by shutdown: re-queued", job_id)
            outcome = "interrupted"
            with contextlib.suppress(Exception):
                await asyncio.shield(self._requeue_interrupted(job_id))
            raise
        except Exception:
            logger.exception("Unexpected error while finalising job %s", job_id)
            with contextlib.suppress(Exception):
                outcome = await self._fail(job_id, RuntimeError("Erreur interne du worker"))
        finally:
            self._cancel_requested.discard(job_id)
            self.stats.in_flight -= 1
            WORKER_INFLIGHT.dec()
            JOB_DURATION_SECONDS.labels(kind=kind, status=outcome).observe(time.perf_counter() - started)

    async def _requeue_interrupted(self, job_id: uuid.UUID) -> None:
        """Put a job interrupted by shutdown back in the queue without consuming an attempt."""
        async with get_sessionmaker()() as session:
            job = await session.get(IngestionJob, job_id)
            if job is None or job.status != JobStatus.running:
                return
            await requeue_without_attempt(session, job)
            await session.commit()

    async def _finish_cancelled(self, job_id: uuid.UUID) -> None:
        async with get_sessionmaker()() as session:
            job = await session.get(IngestionJob, job_id)
            if job is None or job.status != JobStatus.running:
                return
            await mark_cancelled(session, job, "Traitement annulé à la demande d'un utilisateur")
            await session.commit()
        self.stats.cancelled += 1
        logger.warning("Job %s cancelled on request", job_id)

    async def _fail(self, job_id: uuid.UUID, exc: BaseException) -> str:
        """Record a failed attempt.

        Returns the outcome: ``retried`` | ``requeued`` (busy project lock) | ``failed`` | ``dead``.
        """
        if isinstance(exc, TimeoutError):
            error: BaseException = RuntimeError(
                f"Délai de traitement dépassé ({settings.worker_job_timeout_seconds:.0f} s)"
            )
            retryable = True
        elif isinstance(exc, NotImplementedError):
            error = RuntimeError(str(exc) or "Traitement non disponible sur cette instance")
            retryable = False
        else:
            error = exc
            retryable = not isinstance(exc, PermanentJobError)
        async with get_sessionmaker()() as session:
            job = await session.get(IngestionJob, job_id)
            if job is None:
                return "missing"
            if is_lock_timeout(exc):
                waits = int((job.payload or {}).get(LOCK_WAITS_PAYLOAD_KEY, 0)) + 1
                if waits <= MAX_LOCK_WAITS:
                    job.payload = {**(job.payload or {}), LOCK_WAITS_PAYLOAD_KEY: waits}
                    await requeue_without_attempt(
                        session,
                        job,
                        delay_seconds=backoff_delay(min(waits, 3)),
                        error=LOCK_BUSY_MESSAGE,
                    )
                    await session.commit()
                    self.stats.requeued += 1
                    logger.info(
                        "Job %s re-queued: project lock busy (wait %d/%d)", job_id, waits, MAX_LOCK_WAITS
                    )
                    return "requeued"
                error = RuntimeError("Verrou du projet indisponible trop longtemps")
                retryable = True
            will_retry = await mark_failed(session, job, error, retryable=retryable)
            status = job.status
            await session.commit()
        if will_retry:
            self.stats.retried += 1
            logger.warning(
                "Job %s failed (attempt %d/%d), retry scheduled: %s",
                job_id,
                job.attempts,
                job.max_attempts,
                error,
            )
            return "retried"
        if status == JobStatus.dead:
            self.stats.dead += 1
            logger.error("Job %s dead-lettered after %d attempts: %s", job_id, job.attempts, error)
            return "dead"
        self.stats.failed += 1
        logger.error("Job %s failed permanently: %s", job_id, error)
        return "failed"

    # -- background loops -------------------------------------------------------------------------------
    async def _write_heartbeat(self) -> None:
        values = {
            "hostname": self.hostname,
            "pid": self.pid,
            "version": settings.app_version,
            "concurrency": self.concurrency,
            "in_flight": self.stats.in_flight,
            "stats": {
                "succeeded": self.stats.succeeded,
                "failed": self.stats.failed,
                "dead": self.stats.dead,
                "retried": self.stats.retried,
                "requeued": self.stats.requeued,
                "cancelled": self.stats.cancelled,
                "running_jobs": [str(job_id) for job_id in self._running],
            },
            "stopping": self.stop_event.is_set(),
            "last_seen_at": func.now(),
        }
        stmt = pg_insert(WorkerHeartbeat).values(
            worker_id=self.worker_id, started_at=self.started_at, **values
        )
        stmt = stmt.on_conflict_do_update(index_elements=[WorkerHeartbeat.worker_id], set_=values)
        async with get_sessionmaker()() as session:
            await session.execute(stmt)
            await session.commit()

    async def _remove_heartbeat(self) -> None:
        async with get_sessionmaker()() as session:
            await session.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == self.worker_id))
            await session.commit()

    async def _update_queue_gauges(self) -> None:
        async with get_sessionmaker()() as session:
            stats = await queue_stats(session)
        QUEUE_JOBS.clear()
        for status, kinds in stats.by_status.items():
            for kind, count in kinds.items():
                QUEUE_JOBS.labels(status=status, kind=kind).set(count)
        QUEUE_OLDEST_AGE_SECONDS.clear()
        for kind, age in stats.oldest_queued_age_seconds.items():
            QUEUE_OLDEST_AGE_SECONDS.labels(kind=kind).set(age)

    async def heartbeat_once(self) -> None:
        """Refresh job locks, honour cancel requests, publish the heartbeat row and queue gauges."""
        self._last_heartbeat = time.monotonic()
        WORKER_LAST_LOOP_TIMESTAMP.set(time.time())
        try:
            async with get_sessionmaker()() as session:
                refreshed = await refresh_locks(session, self.worker_id)
            for item in refreshed:
                task = self._running.get(item.job_id)
                if item.cancel_requested and task is not None and item.job_id not in self._cancel_requested:
                    logger.warning("Cancellation requested for job %s: stopping it", item.job_id)
                    self._cancel_requested.add(item.job_id)
                    task.cancel()
            await self._write_heartbeat()
            await self._update_queue_gauges()
            self._db_ok = True
        except Exception as exc:
            self._db_ok = False
            logger.warning("Heartbeat failed (database unavailable?): %s", exc)
        now = time.monotonic()
        if now - self._last_log >= settings.worker_heartbeat_seconds:
            self._last_log = now
            logger.info(
                "heartbeat worker=%s uptime=%.0fs in_flight=%d succeeded=%d failed=%d dead=%d retried=%d",
                self.worker_id,
                now - self.stats.started_at,
                self.stats.in_flight,
                self.stats.succeeded,
                self.stats.failed,
                self.stats.dead,
                self.stats.retried,
            )

    async def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            await self.heartbeat_once()
            await self._sleep(self.heartbeat_interval)

    async def _reaper_loop(self) -> None:
        interval = max(1.0, min(60.0, self.stale_lock_seconds / 4))
        while not self.stop_event.is_set():
            try:
                async with get_sessionmaker()() as session:
                    result = await reap_stale_jobs(session, self.stale_lock_seconds)
                if result.total:
                    logger.warning(
                        "Stale jobs recovered: requeued=%d dead=%d cancelled=%d",
                        len(result.requeued),
                        len(result.dead),
                        len(result.cancelled),
                    )
            except Exception as exc:
                logger.warning("Stale job check failed: %s", exc)
            await self._sleep(interval)

    async def _scheduler_loop(self) -> None:
        if not self.schedule:
            await self.stop_event.wait()
            return
        tick = max(1.0, min(60.0, min(spec.interval_seconds for spec in self.schedule)))
        await self._sleep(min(30.0, tick))
        while not self.stop_event.is_set():
            for spec in self.schedule:
                if self.stop_event.is_set():
                    break
                try:
                    await run_singleton_task(spec, self.worker_id)
                except Exception:
                    logger.exception("Scheduled task %s could not run", spec.name)
            await self._sleep(tick)


async def main() -> None:
    setup_logging(settings.log_level)
    setup_tracing("orbit-worker")
    worker = Worker()
    server: InternalServer | None = None
    if settings.worker_metrics_port > 0:
        server = InternalServer(
            str(opt("metrics_host", "0.0.0.0")), settings.worker_metrics_port, worker.health
        )
        try:
            await server.start()
            logger.info("Worker probes on :%d (/healthz, /metrics)", settings.worker_metrics_port)
        except OSError as exc:
            logger.warning("Worker internal endpoint disabled: %s", exc)
            server = None
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)
    try:
        await worker.run()
    finally:
        if server is not None:
            await server.close()
        with contextlib.suppress(Exception):
            from app.search import opensearch

            await opensearch.close_client()
        with contextlib.suppress(Exception):
            from app.memory import short_term

            await short_term.close_valkey()
        with contextlib.suppress(Exception):
            from app.llm import client as llm_client

            await llm_client.close()
        await dispose_engine()
        shutdown_tracing()


if __name__ == "__main__":
    asyncio.run(main())
