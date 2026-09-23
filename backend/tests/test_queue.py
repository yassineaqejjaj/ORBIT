"""Postgres job queue: claim with SKIP LOCKED, retries with backoff, steps, stale recovery."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from app.db import get_sessionmaker, utcnow
from app.enums import JobKind, JobStatus
from app.ingestion.queue import (
    append_step,
    backoff_delay,
    claim_next_job,
    enqueue_job,
    mark_failed,
    mark_succeeded,
    requeue_stale_jobs,
    track_step,
)
from app.models import IngestionJob


@pytest_asyncio.fixture
async def project_id(project: dict) -> uuid.UUID:  # type: ignore[type-arg]
    async with get_sessionmaker()() as session:
        await session.execute(delete(IngestionJob))
        await session.commit()
    return uuid.UUID(str(project["id"]))


async def _enqueue(project_id: uuid.UUID, **kwargs: object) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        job = await enqueue_job(session, project_id, JobKind.ingest, **kwargs)  # type: ignore[arg-type]
        await session.commit()
        return job.id


async def _get(job_id: uuid.UUID) -> IngestionJob:
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        return job


async def test_enqueue_and_claim(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id, payload={"source": "upload"})
    queued = await _get(job_id)
    assert queued.status == JobStatus.queued
    assert queued.attempts == 0
    assert queued.payload == {"source": "upload"}

    async with get_sessionmaker()() as session:
        claimed = await claim_next_job(session, "worker-a")
    assert claimed is not None and claimed.id == job_id
    stored = await _get(job_id)
    assert stored.status == JobStatus.running
    assert stored.attempts == 1
    assert stored.locked_by == "worker-a"
    assert stored.started_at is not None

    async with get_sessionmaker()() as session:
        assert await claim_next_job(session, "worker-b") is None


async def test_claim_skips_locked_rows(project_id: uuid.UUID) -> None:
    first = await _enqueue(project_id)
    second = await _enqueue(project_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as holder:
        locked = await holder.scalar(select(IngestionJob).where(IngestionJob.id == first).with_for_update())
        assert locked is not None
        async with sessionmaker() as other:
            claimed = await claim_next_job(other, "worker-b")
        assert claimed is not None and claimed.id == second
        await holder.rollback()


async def test_concurrent_claims_never_share_a_job(project_id: uuid.UUID) -> None:
    ids = {await _enqueue(project_id) for _ in range(6)}

    async def claim(worker: str) -> uuid.UUID | None:
        async with get_sessionmaker()() as session:
            job = await claim_next_job(session, worker)
            return job.id if job else None

    results = await asyncio.gather(*(claim(f"w{i}") for i in range(8)))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == len(set(claimed)) == 6
    assert set(claimed) == ids


async def test_future_jobs_are_not_claimed(project_id: uuid.UUID) -> None:
    await _enqueue(project_id, run_after=utcnow() + timedelta(minutes=5))
    async with get_sessionmaker()() as session:
        assert await claim_next_job(session, "w") is None


async def test_retry_with_backoff_then_final_failure(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id, max_attempts=3)
    sessionmaker = get_sessionmaker()
    for attempt in (1, 2, 3):
        async with sessionmaker() as session:
            job = await claim_next_job(session, "w")
            assert job is not None and job.attempts == attempt
            will_retry = await mark_failed(session, job, RuntimeError(f"échec {attempt}"))
            await session.commit()
        stored = await _get(job_id)
        assert stored.error == f"échec {attempt}"
        assert stored.locked_by is None
        if attempt < 3:
            assert will_retry
            assert stored.status == JobStatus.queued
            assert stored.run_after > utcnow() + timedelta(seconds=3)
            async with sessionmaker() as session:
                assert await claim_next_job(session, "w") is None  # still backing off
                await session.execute(
                    update(IngestionJob).where(IngestionJob.id == job_id).values(run_after=utcnow())
                )
                await session.commit()
        else:
            assert not will_retry
            assert stored.status == JobStatus.failed
            assert stored.finished_at is not None


async def test_permanent_failure_is_not_retried(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        job = await claim_next_job(session, "w")
        assert job is not None
        assert not await mark_failed(session, job, "Format non pris en charge", retryable=False)
        await session.commit()
    stored = await _get(job_id)
    assert stored.status == JobStatus.failed
    assert stored.attempts == 1


async def test_success_and_steps(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        job = await claim_next_job(session, "w")
        assert job is not None
        await append_step(session, job, "extract", "ok", 12.34, "3 pages")
        async with track_step(session, job, "chunk") as step:
            step.detail = "8 fragments"
        async with track_step(session, job, "extract_memory") as step:
            step.skip("aucune décision détectée")
        with pytest.raises(ValueError):
            async with track_step(session, job, "embed"):
                raise ValueError("modèle indisponible")
        await mark_succeeded(session, job)
        await session.commit()
    stored = await _get(job_id)
    assert stored.status == JobStatus.succeeded
    assert stored.finished_at is not None
    assert [(s["name"], s["status"]) for s in stored.steps] == [
        ("extract", "ok"),
        ("chunk", "ok"),
        ("extract_memory", "skipped"),
        ("embed", "failed"),
    ]
    assert stored.steps[0]["duration_ms"] == 12.3
    assert stored.steps[1]["detail"] == "8 fragments"
    assert stored.steps[3]["detail"] == "modèle indisponible"


async def test_new_attempt_resets_steps(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        job = await claim_next_job(session, "w")
        assert job is not None
        await append_step(session, job, "extract", "failed", 1, "boom")
        await mark_failed(session, job, "boom")
        await session.execute(
            update(IngestionJob).where(IngestionJob.id == job_id).values(run_after=utcnow())
        )
        await session.commit()
    async with get_sessionmaker()() as session:
        job = await claim_next_job(session, "w")
        assert job is not None and job.steps == [] and job.attempts == 2


async def test_stale_running_jobs_are_requeued(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        await claim_next_job(session, "crashed-worker")
    async with get_sessionmaker()() as session:
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(locked_at=utcnow() - timedelta(hours=2))
        )
        await session.commit()
        assert await requeue_stale_jobs(session, older_than_seconds=3600) == 1
    stored = await _get(job_id)
    assert stored.status == JobStatus.queued
    assert stored.locked_by is None


def test_backoff_delay_grows_and_is_capped() -> None:
    delays = [backoff_delay(n, jitter=False) for n in range(1, 12)]
    assert delays[:3] == [5.0, 10.0, 20.0]
    assert max(delays) == 600.0
    assert all(4.0 <= backoff_delay(1) <= 6.0 for _ in range(20))
