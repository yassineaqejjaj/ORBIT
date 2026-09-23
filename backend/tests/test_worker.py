"""Worker loop: claims jobs, runs the pipeline, records success/failure, stops gracefully."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db import get_sessionmaker
from app.enums import JobKind, JobStatus
from app.ingestion import pipeline
from app.ingestion.queue import PermanentJobError, enqueue_job
from app.models import IngestionJob
from app.worker import Worker


@pytest_asyncio.fixture
async def project_id(project: dict) -> uuid.UUID:  # type: ignore[type-arg]
    async with get_sessionmaker()() as session:
        await session.execute(delete(IngestionJob))
        await session.commit()
    return uuid.UUID(str(project["id"]))


async def _enqueue(project_id: uuid.UUID, payload: dict) -> uuid.UUID:  # type: ignore[type-arg]
    async with get_sessionmaker()() as session:
        job = await enqueue_job(session, project_id, JobKind.reindex, payload=payload, max_attempts=2)
        await session.commit()
        return job.id


async def _wait_for(
    job_ids: list[uuid.UUID], statuses: set[JobStatus], timeout: float = 15
) -> list[IngestionJob]:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        async with get_sessionmaker()() as session:
            jobs = [await session.get(IngestionJob, jid) for jid in job_ids]
        if all(j is not None and j.status in statuses for j in jobs):
            return [j for j in jobs if j is not None]
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"jobs not finished: {[(j.id, j.status) for j in jobs if j]}")
        await asyncio.sleep(0.2)


async def test_worker_processes_jobs(project_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_job(session, job):  # type: ignore[no-untyped-def]
        mode = job.payload.get("mode")
        if mode == "permanent":
            raise PermanentJobError("Fichier illisible")
        if mode == "unavailable":
            raise NotImplementedError("Traitement non disponible")
        job.payload = {**job.payload, "done": True}

    monkeypatch.setattr(pipeline, "run_job", fake_run_job)
    ok = await _enqueue(project_id, {"mode": "ok"})
    permanent = await _enqueue(project_id, {"mode": "permanent"})
    unavailable = await _enqueue(project_id, {"mode": "unavailable"})

    worker = Worker(concurrency=2, worker_id="test-worker")
    runner = asyncio.create_task(worker.run())
    try:
        jobs = await _wait_for([ok, permanent, unavailable], {JobStatus.succeeded, JobStatus.failed})
    finally:
        worker.request_stop()
        await asyncio.wait_for(runner, timeout=20)

    by_id = {j.id: j for j in jobs}
    assert by_id[ok].status == JobStatus.succeeded
    assert by_id[ok].payload["done"] is True
    assert by_id[permanent].status == JobStatus.failed
    assert by_id[permanent].error == "Fichier illisible"
    assert by_id[permanent].attempts == 1
    assert by_id[unavailable].status == JobStatus.failed
    assert by_id[unavailable].error == "Traitement non disponible"
    assert worker.stats.succeeded == 1
    assert worker.stats.failed == 2


async def test_transient_failure_is_retried(project_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    async def flaky(session, job):  # type: ignore[no-untyped-def]
        raise ConnectionError("OpenSearch indisponible")

    monkeypatch.setattr(pipeline, "run_job", flaky)
    job_id = await _enqueue(project_id, {})
    worker = Worker(concurrency=1, worker_id="test-worker-retry")
    runner = asyncio.create_task(worker.run())
    try:
        await _wait_for([job_id], {JobStatus.queued, JobStatus.failed})
        deadline = asyncio.get_running_loop().time() + 10
        while worker.stats.retried < 1 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
    finally:
        worker.request_stop()
        await asyncio.wait_for(runner, timeout=20)
    async with get_sessionmaker()() as session:
        stored = await session.get(IngestionJob, job_id)
    assert stored is not None
    assert worker.stats.retried == 1
    assert stored.status == JobStatus.queued
    assert stored.attempts == 1
    assert stored.error == "OpenSearch indisponible"
