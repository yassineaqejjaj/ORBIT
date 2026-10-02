"""ORBIT worker: processes the Postgres job queue (``python -m app.worker``).

* ``ORBIT_WORKER_CONCURRENCY`` slots claim jobs with ``SELECT … FOR UPDATE SKIP LOCKED`` and run
  ``app.ingestion.pipeline.run_job`` (one DB session per job, job timeout enforced);
* failures are retried with exponential backoff (``app.ingestion.queue.mark_failed``);
* stale ``running`` jobs (crashed worker) are re-queued periodically;
* memory maintenance (``app.memory.lifecycle.run_periodic_maintenance``) runs on an interval;
* heartbeat log line every ``ORBIT_WORKER_HEARTBEAT_SECONDS``;
* SIGTERM/SIGINT: stop claiming, let in-flight jobs finish within
  ``ORBIT_WORKER_SHUTDOWN_GRACE_SECONDS``, then cancel them (they are re-queued as stale later).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
import uuid
from dataclasses import dataclass, field

from app.config import settings
from app.db import dispose_engine, get_sessionmaker, utcnow
from app.enums import JobStatus
from app.ingestion import pipeline
from app.ingestion.queue import (
    PermanentJobError,
    claim_next_job,
    mark_failed,
    mark_succeeded,
    requeue_stale_jobs,
)
from app.models import IngestionJob
from app.observability.logging_setup import setup_logging
from app.observability.metrics import WORKER_INFLIGHT
from app.observability.tracing import get_tracer, setup_tracing, shutdown_tracing

logger = logging.getLogger("orbit.worker")

STALE_CHECK_INTERVAL_SECONDS = 60.0
ERROR_BACKOFF_SECONDS = 5.0


@dataclass
class WorkerStats:
    started_at: float = field(default_factory=time.monotonic)
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    in_flight: int = 0


class Worker:
    def __init__(self, concurrency: int | None = None, worker_id: str | None = None) -> None:
        self.concurrency = concurrency or settings.worker_concurrency
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.stop_event = asyncio.Event()
        self.stats = WorkerStats()
        self._tracer = get_tracer("orbit.worker")
        self._maintenance_unavailable_logged = False

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
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)

    async def run(self) -> None:
        logger.info("Worker %s starting (concurrency=%d)", self.worker_id, self.concurrency)
        await self._prepare_indices()
        slots = [asyncio.create_task(self._slot(i), name=f"slot-{i}") for i in range(self.concurrency)]
        background = [
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
            asyncio.create_task(self._stale_requeue_loop(), name="stale-requeue"),
            asyncio.create_task(self._maintenance_loop(), name="maintenance"),
        ]
        await self.stop_event.wait()

        # Stop claiming; give running jobs a grace period.
        _done, pending = await asyncio.wait(slots, timeout=settings.worker_shutdown_grace_seconds)
        for task in pending:
            task.cancel()
        for task in background:
            task.cancel()
        await asyncio.gather(*pending, *background, return_exceptions=True)
        logger.info(
            "Worker %s stopped (succeeded=%d failed=%d retried=%d)",
            self.worker_id,
            self.stats.succeeded,
            self.stats.failed,
            self.stats.retried,
        )

    async def _prepare_indices(self) -> None:
        from app.search import opensearch

        try:
            await opensearch.ensure_indices()
        except NotImplementedError:
            logger.warning("OpenSearch index setup not implemented yet — skipped")
        except Exception as exc:  # OpenSearch may still be starting: the API also ensures indices
            logger.warning("OpenSearch index setup failed at worker start: %s", exc)

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

    async def _process(self, job_id: uuid.UUID) -> None:
        sessionmaker = get_sessionmaker()
        self.stats.in_flight += 1
        WORKER_INFLIGHT.inc()
        started = time.perf_counter()
        try:
            async with sessionmaker() as session:
                job = await session.get(IngestionJob, job_id)
                if job is None:
                    return
                label = (
                    f"{job.kind} job={job.id} doc={job.document_id} attempt={job.attempts}/{job.max_attempts}"
                )
                logger.info("Running %s", label)
                with self._tracer.start_as_current_span(f"job.{job.kind}") as span:
                    span.set_attribute("orbit.job_id", str(job.id))
                    span.set_attribute("orbit.project_id", str(job.project_id))
                    span.set_attribute("orbit.attempt", job.attempts)
                    try:
                        await asyncio.wait_for(
                            pipeline.run_job(session, job), timeout=settings.worker_job_timeout_seconds
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        span.record_exception(exc)
                        await session.rollback()
                        await self._fail(job_id, exc)
                        return
                    await mark_succeeded(session, job)
                    await session.commit()
                    self.stats.succeeded += 1
                    logger.info("Succeeded %s in %.0f ms", label, (time.perf_counter() - started) * 1000)
        except asyncio.CancelledError:
            logger.warning("Job %s interrupted by shutdown: re-queued", job_id)
            with contextlib.suppress(Exception):
                await asyncio.shield(self._requeue_interrupted(job_id))
            raise
        except Exception:
            logger.exception("Unexpected error while finalising job %s", job_id)
            with contextlib.suppress(Exception):
                await self._fail(job_id, RuntimeError("Erreur interne du worker"))
        finally:
            self.stats.in_flight -= 1
            WORKER_INFLIGHT.dec()

    async def _requeue_interrupted(self, job_id: uuid.UUID) -> None:
        """Put a job interrupted by shutdown back in the queue without consuming an attempt."""
        async with get_sessionmaker()() as session:
            job = await session.get(IngestionJob, job_id)
            if job is None or job.status != JobStatus.running:
                return
            job.status = JobStatus.queued
            job.attempts = max(0, job.attempts - 1)
            job.locked_by = None
            job.locked_at = None
            job.run_after = utcnow()
            await session.commit()

    async def _fail(self, job_id: uuid.UUID, exc: BaseException) -> None:
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
                return
            will_retry = await mark_failed(session, job, error, retryable=retryable)
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
        else:
            self.stats.failed += 1
            logger.error("Job %s failed permanently: %s", job_id, error)

    # -- background loops -------------------------------------------------------------------------------
    async def _feed_maintenance(self) -> None:
        try:
            summary = await _feed_maintenance_once()
            if summary:
                logger.info("Feed maintenance: %s", summary)
        except Exception:
            logger.exception("Feed maintenance failed")

    async def _connector_maintenance(self) -> None:
        try:
            summary = await _connector_maintenance_once()
            if summary:
                logger.info("Connector maintenance: %s", summary)
        except Exception:
            logger.exception("Connector maintenance failed")

    async def _heartbeat(self) -> None:
        while not self.stop_event.is_set():
            await self._sleep(settings.worker_heartbeat_seconds)
            if self.stop_event.is_set():
                break
            uptime = time.monotonic() - self.stats.started_at
            logger.info(
                "heartbeat worker=%s uptime=%.0fs in_flight=%d succeeded=%d failed=%d retried=%d",
                self.worker_id,
                uptime,
                self.stats.in_flight,
                self.stats.succeeded,
                self.stats.failed,
                self.stats.retried,
            )

    async def _stale_requeue_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                async with get_sessionmaker()() as session:
                    count = await requeue_stale_jobs(session, settings.worker_stale_lock_seconds)
                if count:
                    logger.warning("Re-queued %d stale job(s)", count)
            except Exception as exc:
                logger.warning("Stale job check failed: %s", exc)
            await self._sleep(STALE_CHECK_INTERVAL_SECONDS)

    async def _maintenance_loop(self) -> None:
        from app.memory import lifecycle

        await self._sleep(min(30.0, settings.worker_maintenance_interval_seconds))
        while not self.stop_event.is_set():
            try:
                async with get_sessionmaker()() as session:
                    summary = await lifecycle.run_periodic_maintenance(session)
                    await session.commit()
                if summary:
                    logger.info("Memory maintenance: %s", summary)
            except NotImplementedError:
                if not self._maintenance_unavailable_logged:
                    logger.info("Memory maintenance not implemented yet — skipped")
                    self._maintenance_unavailable_logged = True
            except Exception:
                logger.exception("Memory maintenance failed")
            await self._feed_maintenance()
            await self._connector_maintenance()
            await self._sleep(settings.worker_maintenance_interval_seconds)


async def _feed_maintenance_once() -> dict[str, int]:
    """Change feed upkeep (docs/FEATURES.md F2): stale documents + due digest e-mails."""
    from app.features.feed.service import run_feed_maintenance

    async with get_sessionmaker()() as session:
        summary = await run_feed_maintenance(session)
        await session.commit()
    return summary


async def _connector_maintenance_once() -> dict[str, int]:
    """Connectors (docs/FEATURES.md F5): queue the scheduled syncs that are due, close orphan runs."""
    from app.connectors.service import run_connector_maintenance

    async with get_sessionmaker()() as session:
        summary = await run_connector_maintenance(session)
        await session.commit()
    return summary


def _start_metrics_server() -> None:
    if settings.worker_metrics_port <= 0:
        return
    try:
        from prometheus_client import start_http_server

        start_http_server(settings.worker_metrics_port)
        logger.info("Worker metrics exposed on :%d/metrics", settings.worker_metrics_port)
    except OSError as exc:
        logger.warning("Worker metrics endpoint disabled: %s", exc)


async def main() -> None:
    setup_logging(settings.log_level)
    setup_tracing("orbit-worker")
    _start_metrics_server()
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)
    try:
        await worker.run()
    finally:
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
