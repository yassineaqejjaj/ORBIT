"""Queue robustness: fair claim, priorities, poison pill / dead letter, lock heartbeat, retry and cancel."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, update

from app.db import get_sessionmaker, utcnow
from app.enums import DocumentStatus, JobKind, JobStatus, SourceKind
from app.ingestion.queue import (
    POISON_PILL_CRASHES,
    JobStateError,
    cancel_job,
    claim_next_job,
    enqueue_job,
    mark_failed,
    mark_succeeded,
    queue_stats,
    reap_stale_jobs,
    refresh_locks,
    requeue_without_attempt,
    retry_job,
)
from app.models import Document, IngestionJob, Project, Source


@pytest_asyncio.fixture
async def project_id(project: dict) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        await session.execute(delete(IngestionJob))
        await session.commit()
    return uuid.UUID(str(project["id"]))


@pytest_asyncio.fixture
async def other_project_id(project_id: uuid.UUID) -> AsyncIterator[uuid.UUID]:
    async with get_sessionmaker()() as session:
        other = Project(slug=f"fair-{uuid.uuid4().hex[:8]}", name="Projet équité")
        session.add(other)
        await session.commit()
        other_id = other.id
    yield other_id
    async with get_sessionmaker()() as session:
        await session.execute(delete(Project).where(Project.id == other_id))
        await session.commit()


async def _enqueue(project_id: uuid.UUID | None, **kwargs: object) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        job = await enqueue_job(session, project_id, JobKind.ingest, **kwargs)  # type: ignore[arg-type]
        await session.commit()
        return job.id


async def _get(job_id: uuid.UUID) -> IngestionJob:
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        return job


async def _claim(worker: str = "w") -> IngestionJob | None:
    async with get_sessionmaker()() as session:
        return await claim_next_job(session, worker)


async def _expire_lock(job_id: uuid.UUID, *, hours: float = 2) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(locked_at=utcnow() - timedelta(hours=hours))
        )
        await session.commit()


async def _make_runnable(job_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(IngestionJob).where(IngestionJob.id == job_id).values(run_after=utcnow())
        )
        await session.commit()


async def _reap(threshold: float = 3600):
    async with get_sessionmaker()() as session:
        return await reap_stale_jobs(session, older_than_seconds=threshold)


# --- Fairness & priorities ---------------------------------------------------------------------------------


async def test_claim_is_fair_across_projects(project_id: uuid.UUID, other_project_id: uuid.UUID) -> None:
    bulk = [await _enqueue(project_id) for _ in range(5)]
    single = await _enqueue(other_project_id)

    first = await _claim("w1")
    assert first is not None and first.id == bulk[0]  # oldest head when no project is busy
    second = await _claim("w2")
    assert second is not None and second.id == single  # the busy project yields to the idle one
    third = await _claim("w3")
    assert third is not None and third.id == bulk[1]


async def test_priority_orders_jobs_within_a_project(project_id: uuid.UUID) -> None:
    low = await _enqueue(project_id, priority=-10)
    normal = await _enqueue(project_id)
    urgent = await _enqueue(project_id, priority=10)
    claimed = [await _claim(f"w{i}") for i in range(3)]
    assert [job.id for job in claimed if job] == [urgent, normal, low]
    stored = await _get(urgent)
    assert stored.priority == 10


async def test_platform_jobs_without_project_are_claimed(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(None, payload={"target": "all"})
    claimed = await _claim()
    assert claimed is not None and claimed.id == job_id and claimed.project_id is None


async def test_claim_falls_back_when_every_head_is_locked(project_id: uuid.UUID) -> None:
    from sqlalchemy import select

    head = await _enqueue(project_id)
    follower = await _enqueue(project_id)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as holder:
        await holder.scalar(select(IngestionJob).where(IngestionJob.id == head).with_for_update())
        claimed = await _claim("w2")
        assert claimed is not None and claimed.id == follower
        await holder.rollback()


async def test_claim_respects_kind_filter(project_id: uuid.UUID) -> None:
    await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        other = await enqueue_job(session, project_id, JobKind.consolidate)
        await session.commit()
    async with get_sessionmaker()() as session:
        claimed = await claim_next_job(session, "w", kinds=[JobKind.consolidate])
    assert claimed is not None and claimed.id == other.id


# --- Crash recovery, poison pill, dead letter -----------------------------------------------------------------


async def test_poison_pill_goes_to_dead_letter(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id, max_attempts=5)
    for crash in range(1, POISON_PILL_CRASHES + 1):
        claimed = await _claim("doomed-worker")
        assert claimed is not None and claimed.id == job_id
        await _expire_lock(job_id)
        result = await _reap()
        stored = await _get(job_id)
        assert stored.crash_count == crash
        if crash < POISON_PILL_CRASHES:
            assert result.requeued == [job_id]
            assert stored.status == JobStatus.queued
            await _make_runnable(job_id)
    assert result.dead == [job_id]
    assert stored.status == JobStatus.dead
    assert stored.finished_at is not None
    assert "abandonné" in (stored.error or "")
    assert await _claim() is None  # never re-claimed


async def test_crash_on_last_attempt_is_dead(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id, max_attempts=1)
    assert await _claim() is not None
    await _expire_lock(job_id)
    result = await _reap()
    assert result.dead == [job_id]
    assert (await _get(job_id)).status == JobStatus.dead


async def test_crash_with_pending_cancel_is_cancelled(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id)
    job = await _claim()
    assert job is not None
    async with get_sessionmaker()() as session:
        stored = await session.get(IngestionJob, job_id)
        assert stored is not None
        await cancel_job(session, stored)
        await session.commit()
    await _expire_lock(job_id)
    result = await _reap()
    assert result.cancelled == [job_id]
    assert (await _get(job_id)).status == JobStatus.cancelled


async def test_lock_heartbeat_prevents_reaping(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id)
    assert await _claim("alive-worker") is not None
    await _expire_lock(job_id)
    async with get_sessionmaker()() as session:
        refreshed = await refresh_locks(session, "alive-worker")
    assert [(r.job_id, r.cancel_requested) for r in refreshed] == [(job_id, False)]
    assert (await _reap(threshold=60)).total == 0
    assert (await _get(job_id)).status == JobStatus.running
    async with get_sessionmaker()() as session:
        assert await refresh_locks(session, "another-worker") == []


async def test_refresh_reports_cancel_requests(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id)
    assert await _claim("w") is not None
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        await cancel_job(session, job)
        await session.commit()
        assert job.status == JobStatus.running and job.cancel_requested_at is not None
    async with get_sessionmaker()() as session:
        refreshed = await refresh_locks(session, "w")
    assert refreshed[0].cancel_requested is True


async def test_requeue_without_attempt_refunds_the_attempt(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        job = await claim_next_job(session, "w")
        assert job is not None and job.attempts == 1
        await requeue_without_attempt(session, job, delay_seconds=30, error="verrou occupé")
        await session.commit()
    stored = await _get(job_id)
    assert stored.status == JobStatus.queued
    assert stored.attempts == 0
    assert stored.error == "verrou occupé"
    assert stored.run_after > utcnow() + timedelta(seconds=20)


# --- Operator actions ---------------------------------------------------------------------------------------


async def test_retry_dead_job_resets_budget(project_id: uuid.UUID) -> None:
    job_id = await _enqueue(project_id, max_attempts=1)
    async with get_sessionmaker()() as session:
        job = await claim_next_job(session, "w")
        assert job is not None
        await mark_failed(session, job, "OpenSearch indisponible")
        await session.commit()
    assert (await _get(job_id)).status == JobStatus.dead
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        await retry_job(session, job)
        await session.commit()
    stored = await _get(job_id)
    assert (stored.status, stored.attempts, stored.crash_count, stored.error) == (
        JobStatus.queued,
        0,
        0,
        None,
    )
    claimed = await _claim()
    assert claimed is not None and claimed.id == job_id


@pytest.mark.parametrize("status", [JobStatus.queued, JobStatus.running, JobStatus.succeeded])
async def test_retry_refused_for_active_or_succeeded(project_id: uuid.UUID, status: JobStatus) -> None:
    job_id = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        job.status = status
        await session.flush()
        with pytest.raises(JobStateError):
            await retry_job(session, job)


async def test_cancel_queued_and_refuse_succeeded(project_id: uuid.UUID) -> None:
    queued = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, queued)
        assert job is not None
        await cancel_job(session, job, reason="Annulé par test")
        await session.commit()
    stored = await _get(queued)
    assert stored.status == JobStatus.cancelled and stored.error == "Annulé par test"
    assert await _claim() is None

    done = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        job = await claim_next_job(session, "w")
        assert job is not None
        await mark_succeeded(session, job)
        await session.commit()
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, done)
        assert job is not None
        with pytest.raises(JobStateError):
            await cancel_job(session, job)


async def test_queue_stats(project_id: uuid.UUID) -> None:
    await _enqueue(project_id)
    await _enqueue(project_id, run_after=utcnow() + timedelta(hours=1))
    running = await _enqueue(project_id)
    async with get_sessionmaker()() as session:
        await session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == running)
            .values(status=JobStatus.running, run_after=utcnow() - timedelta(minutes=5))
        )
        await session.commit()
        stats = await queue_stats(session)
    assert stats.by_status["queued"]["ingest"] == 2
    assert stats.total(JobStatus.running) == 1
    assert stats.total(JobStatus.dead) == 0
    assert 0 <= stats.oldest_queued_age_seconds["ingest"] < 60


async def test_dead_ingest_job_fails_its_document_and_retry_resets_it(project_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        source = Source(project_id=project_id, name=f"src-{uuid.uuid4().hex[:6]}", kind=SourceKind.document)
        session.add(source)
        await session.flush()
        document = Document(
            project_id=project_id, source_id=source.id, title="Rapport", status=DocumentStatus.processing
        )
        session.add(document)
        await session.flush()
        job = await enqueue_job(session, project_id, JobKind.ingest, document.id, max_attempts=1)
        await session.commit()
        job_id, document_id = job.id, document.id
    assert await _claim() is not None
    await _expire_lock(job_id)
    assert (await _reap()).dead == [job_id]
    async with get_sessionmaker()() as session:
        stored_doc = await session.get(Document, document_id)
        assert stored_doc is not None and stored_doc.status == DocumentStatus.failed
        assert "abandonné" in (stored_doc.status_reason or "")
        stored_job = await session.get(IngestionJob, job_id)
        assert stored_job is not None
        await retry_job(session, stored_job)
        await session.commit()
        await session.refresh(stored_doc)
        assert stored_doc.status == DocumentStatus.pending and stored_doc.status_reason is None
        await cancel_job(session, stored_job)
        await session.commit()
        await session.refresh(stored_doc)
        assert stored_doc.status == DocumentStatus.failed
