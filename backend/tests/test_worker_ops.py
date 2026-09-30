"""Worker operations: cancellation, lock_timeout re-queue, heartbeats, probes, singleton scheduled tasks."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.db import get_sessionmaker
from app.enums import JobKind, JobStatus
from app.ingestion import pipeline
from app.ingestion.queue import cancel_job, enqueue_job
from app.models import IngestionJob
from app.models.job import ScheduledTask, WorkerHeartbeat
from app.observability.internal_server import InternalServer
from app.worker import (
    LOCK_BUSY_MESSAGE,
    LOCK_WAITS_PAYLOAD_KEY,
    ScheduledSpec,
    TaskUnavailable,
    Worker,
    is_lock_timeout,
    retention_task,
    run_singleton_task,
)


@pytest_asyncio.fixture
async def project_id(project: dict) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        await session.execute(delete(IngestionJob))
        await session.commit()
    return uuid.UUID(str(project["id"]))


async def _enqueue(project_id: uuid.UUID, payload: dict[str, Any] | None = None) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        job = await enqueue_job(session, project_id, JobKind.reindex, payload=payload or {})
        await session.commit()
        return job.id


async def _get(job_id: uuid.UUID) -> IngestionJob:
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        return job


async def _until(predicate: Callable[[], Awaitable[bool]], timeout: float = 15) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.1)


def _worker(name: str, **kwargs: Any) -> Worker:
    return Worker(
        concurrency=1,
        worker_id=f"{name}-{uuid.uuid4().hex[:6]}",
        heartbeat_interval=0.2,
        schedule=[],
        **kwargs,
    )


async def test_running_job_is_cancelled_on_request(
    project_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()

    async def slow(session, job):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(pipeline, "run_job", slow)
    job_id = await _enqueue(project_id)
    worker = _worker("cancel")
    runner = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=10)
        async with get_sessionmaker()() as session:
            job = await session.get(IngestionJob, job_id)
            assert job is not None
            await cancel_job(session, job)
            await session.commit()

        async def _cancelled() -> bool:
            return (await _get(job_id)).status == JobStatus.cancelled

        await _until(_cancelled)
    finally:
        worker.request_stop()
        await asyncio.wait_for(runner, timeout=20)
    stored = await _get(job_id)
    assert stored.locked_by is None and stored.finished_at is not None
    assert worker.stats.cancelled == 1


async def test_busy_project_lock_requeues_without_consuming_an_attempt(
    project_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = func.hashtextextended(f"orbit:test-lock:{project_id}", 0)

    async def needs_lock(session, job):
        await session.execute(select(func.pg_advisory_xact_lock(key)))

    monkeypatch.setattr(pipeline, "run_job", needs_lock)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as holder:
        await holder.execute(select(func.pg_advisory_xact_lock(key)))  # held until rollback
        job_id = await _enqueue(project_id)
        worker = _worker("lock", lock_timeout_ms=200)
        runner = asyncio.create_task(worker.run())
        try:

            async def _requeued() -> bool:
                return worker.stats.requeued >= 1

            await _until(_requeued)
        finally:
            worker.request_stop()
            await asyncio.wait_for(runner, timeout=20)
        await holder.rollback()
    stored = await _get(job_id)
    assert stored.status == JobStatus.queued
    assert stored.attempts == 0
    assert stored.payload[LOCK_WAITS_PAYLOAD_KEY] >= 1
    assert stored.error == LOCK_BUSY_MESSAGE
    assert worker.stats.failed == 0 and worker.stats.retried == 0


async def test_worker_publishes_and_removes_its_heartbeat(project_id: uuid.UUID) -> None:
    worker = _worker("hb")
    runner = asyncio.create_task(worker.run())

    async def _row() -> WorkerHeartbeat | None:
        async with get_sessionmaker()() as session:
            return await session.get(WorkerHeartbeat, worker.worker_id)

    async def _published() -> bool:
        return await _row() is not None

    try:
        await _until(_published)
        row = await _row()
        assert row is not None and row.concurrency == 1 and row.stopping is False
        healthy, details = await worker.health()
        assert healthy and details["database"] == "ok"
    finally:
        worker.request_stop()
        await asyncio.wait_for(runner, timeout=20)
    assert await _row() is None


async def test_internal_server_serves_health_and_metrics() -> None:
    state = {"healthy": True}

    async def health() -> tuple[bool, dict[str, Any]]:
        return state["healthy"], {"worker_id": "probe-test"}

    server = InternalServer("127.0.0.1", 0, health)
    await server.start()
    try:
        base = f"http://127.0.0.1:{server.bound_port}"
        async with httpx.AsyncClient(base_url=base, timeout=5) as client:
            ok = await client.get("/healthz")
            assert ok.status_code == 200 and ok.json() == {"status": "ok", "worker_id": "probe-test"}
            state["healthy"] = False
            assert (await client.get("/healthz")).status_code == 503
            metrics = await client.get("/metrics")
            assert metrics.status_code == 200 and "orbit_ingestion_jobs_total" in metrics.text
            assert (await client.get("/nope")).status_code == 404
            assert (await client.post("/healthz")).status_code == 405
    finally:
        await server.close()


async def test_singleton_task_runs_once_across_replicas(app: object) -> None:
    name = f"test-task-{uuid.uuid4().hex[:6]}"
    runs: list[str] = []
    release = asyncio.Event()

    async def task(session):
        runs.append("run")
        await release.wait()
        return {"items": 3}

    spec = ScheduledSpec(name, 3600.0, task)
    first = asyncio.create_task(run_singleton_task(spec, "replica-a"))
    await asyncio.sleep(0.3)
    assert await run_singleton_task(spec, "replica-b") == "locked"
    release.set()
    assert await first == "ok"
    assert await run_singleton_task(spec, "replica-b") == "not_due"
    assert await run_singleton_task(spec, "replica-b", force=True) == "ok"
    assert runs == ["run", "run"]
    async with get_sessionmaker()() as session:
        row = await session.get(ScheduledTask, name)
        assert row is not None
        assert (row.last_status, row.holder, row.last_summary) == ("ok", "replica-b", {"items": 3})
        await session.delete(row)
        await session.commit()


async def test_singleton_task_records_failures_and_unavailability(app: object) -> None:
    async def broken(session):
        raise RuntimeError("boom")

    async def missing(session):
        raise TaskUnavailable("absent")

    names = [f"test-broken-{uuid.uuid4().hex[:6]}", f"test-missing-{uuid.uuid4().hex[:6]}"]
    assert await run_singleton_task(ScheduledSpec(names[0], 60.0, broken), "r") == "failed"
    assert await run_singleton_task(ScheduledSpec(names[1], 60.0, missing), "r") == "skipped"
    async with get_sessionmaker()() as session:
        broken_row = await session.get(ScheduledTask, names[0])
        missing_row = await session.get(ScheduledTask, names[1])
        assert broken_row is not None and "boom" in (broken_row.last_error or "")
        assert missing_row is not None and missing_row.last_status == "skipped"
        await session.execute(delete(ScheduledTask).where(ScheduledTask.name.in_(names)))
        await session.commit()


def _retention_installed() -> bool:
    try:
        return importlib.util.find_spec("app.compliance.retention") is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(_retention_installed(), reason="retention module installed")
async def test_retention_hook_is_skipped_when_module_is_absent(app: object) -> None:
    async with get_sessionmaker()() as session:
        with pytest.raises(TaskUnavailable):
            await retention_task(session)


def test_is_lock_timeout_walks_the_exception_chain() -> None:
    class FakePgError(Exception):
        sqlstate = "55P03"

    class Wrapper(Exception):
        def __init__(self, orig: BaseException) -> None:
            super().__init__("wrapped")
            self.orig = orig

    assert is_lock_timeout(Wrapper(FakePgError()))
    try:
        try:
            raise Wrapper(FakePgError())
        except Wrapper:
            raise RuntimeError("current transaction is aborted") from None
    except RuntimeError as exc:
        assert exc.__context__ is not None
        assert is_lock_timeout(exc)
    assert not is_lock_timeout(RuntimeError("other"))
