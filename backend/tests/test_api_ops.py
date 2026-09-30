"""Ops API: job retry/cancel (project editors) and platform status / dead letter (administrators)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest_asyncio
from sqlalchemy import delete, select

from app.db import get_sessionmaker, utcnow
from app.enums import JobKind, JobStatus, SourceKind
from app.ingestion.queue import enqueue_job
from app.models import AuditLog, Document, IngestionJob, Source
from app.models.job import WorkerHeartbeat


@pytest_asyncio.fixture
async def project_id(project: dict) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        await session.execute(delete(IngestionJob))
        await session.commit()
    return uuid.UUID(str(project["id"]))


async def _job(
    project_id: uuid.UUID,
    status: JobStatus,
    *,
    document_id: uuid.UUID | None = None,
    error: str | None = "Échec de test",
) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        job = await enqueue_job(session, project_id, JobKind.ingest, document_id=document_id)
        job.status = status
        job.attempts = job.max_attempts if status == JobStatus.dead else 0
        job.error = error
        if status in (JobStatus.dead, JobStatus.failed, JobStatus.succeeded):
            job.finished_at = utcnow()
        await session.commit()
        return job.id


async def _document(project_id: uuid.UUID, classification: int) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        source = Source(project_id=project_id, name=f"src-{uuid.uuid4().hex[:6]}", kind=SourceKind.document)
        session.add(source)
        await session.flush()
        document = Document(
            project_id=project_id,
            source_id=source.id,
            title="Plan de restructuration",
            classification=classification,
        )
        session.add(document)
        await session.commit()
        return document.id


def _jobs_url(project: dict[str, Any], job_id: uuid.UUID, action: str) -> str:
    return f"/api/v1/projects/{project['slug']}/jobs/{job_id}/{action}"


async def test_retry_and_cancel_lifecycle(
    admin_client: httpx.AsyncClient, project: dict[str, Any], project_id: uuid.UUID
) -> None:
    dead = await _job(project_id, JobStatus.dead)
    retried = await admin_client.post(_jobs_url(project, dead, "retry"))
    assert retried.status_code == 200, retried.text
    body = retried.json()
    assert (body["status"], body["attempts"], body["error"]) == ("queued", 0, None)

    again = await admin_client.post(_jobs_url(project, dead, "retry"))
    assert again.status_code == 409 and again.json()["code"] == "job_not_retryable"

    cancelled = await admin_client.post(_jobs_url(project, dead, "cancel"))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert (await admin_client.post(_jobs_url(project, dead, "cancel"))).json()[
        "code"
    ] == "job_not_cancellable"

    # A cancelled job can be retried again.
    assert (await admin_client.post(_jobs_url(project, dead, "retry"))).json()["status"] == "queued"

    async with get_sessionmaker()() as session:
        actions = list(
            await session.scalars(
                select(AuditLog.action).where(AuditLog.target_id == str(dead)).order_by(AuditLog.created_at)
            )
        )
    assert actions == ["job.retry", "job.cancel", "job.retry"]


async def test_cancel_running_job_requests_stop(
    admin_client: httpx.AsyncClient, project: dict[str, Any], project_id: uuid.UUID
) -> None:
    running = await _job(project_id, JobStatus.running, error=None)
    response = await admin_client.post(_jobs_url(project, running, "cancel"))
    assert response.status_code == 200 and response.json()["status"] == "running"
    async with get_sessionmaker()() as session:
        job = await session.get(IngestionJob, running)
        assert job is not None and job.cancel_requested_at is not None


async def test_job_actions_require_editor_and_visible_job(
    admin_client: httpx.AsyncClient,
    project: dict[str, Any],
    project_id: uuid.UUID,
    make_user: Callable[..., Awaitable[Any]],
    client_for: Callable[[Any], Awaitable[httpx.AsyncClient]],
) -> None:
    viewer = await make_user()
    added = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": viewer.email, "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    viewer_client = await client_for(viewer)
    dead = await _job(project_id, JobStatus.dead)
    assert (await viewer_client.post(_jobs_url(project, dead, "retry"))).status_code == 403
    assert (await viewer_client.post(_jobs_url(project, dead, "cancel"))).status_code == 403
    missing = await admin_client.post(_jobs_url(project, uuid.uuid4(), "retry"))
    assert missing.status_code == 404 and missing.json()["detail"] == "Job introuvable"


async def test_ops_endpoints_are_admin_only(
    make_user: Callable[..., Awaitable[Any]], client_for: Callable[[Any], Awaitable[httpx.AsyncClient]]
) -> None:
    user_client = await client_for(await make_user(clearance=3))
    assert (await user_client.get("/api/v1/ops/status")).status_code == 403
    assert (await user_client.get("/api/v1/ops/jobs/dead-letter")).status_code == 403


async def test_ops_status_reports_queue_workers_and_dependencies(
    admin_client: httpx.AsyncClient, project_id: uuid.UUID
) -> None:
    await _job(project_id, JobStatus.dead)
    await _job(project_id, JobStatus.queued, error=None)
    worker_id = f"status-test-{uuid.uuid4().hex[:6]}"
    async with get_sessionmaker()() as session:
        session.add(
            WorkerHeartbeat(
                worker_id=worker_id, hostname="h", pid=1, version="1.0.0", concurrency=2, in_flight=0
            )
        )
        await session.commit()
    try:
        response = await admin_client.get("/api/v1/ops/status")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["queue"]["dead_letter"] == 1
        assert body["queue"]["totals"]["queued"] == 1
        assert body["queue"]["by_status"]["dead"] == {"ingest": 1}
        worker = next(w for w in body["workers"] if w["worker_id"] == worker_id)
        assert worker["alive"] is True
        dependencies = {d["name"]: d for d in body["dependencies"]}
        assert dependencies["postgres"]["status"] == "ok" and dependencies["postgres"]["required"] is True
        assert dependencies["valkey"]["required"] is False
        assert {i["kind"] for i in body["indices"]} == {"chunks", "memory"}
        assert body["status"] in {"ok", "degraded"}
    finally:
        async with get_sessionmaker()() as session:
            await session.execute(delete(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id))
            await session.commit()


async def test_dead_letter_lists_dead_jobs_and_masks_restricted_documents(
    admin_client: httpx.AsyncClient,
    project: dict[str, Any],
    project_id: uuid.UUID,
    make_user: Callable[..., Awaitable[Any]],
    client_for: Callable[[Any], Awaitable[httpx.AsyncClient]],
) -> None:
    restricted_doc = await _document(project_id, classification=3)
    restricted = await _job(
        project_id, JobStatus.dead, document_id=restricted_doc, error="Contenu confidentiel"
    )
    plain = await _job(project_id, JobStatus.dead)
    await _job(project_id, JobStatus.failed)

    listed = await admin_client.get("/api/v1/ops/jobs/dead-letter", params={"project": project["slug"]})
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["total"] == 2
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[str(plain)]["project_slug"] == project["slug"]
    assert by_id[str(plain)]["max_attempts"] == 3

    low_admin = await client_for(await make_user(is_admin=True, clearance=1))
    masked = (await low_admin.get("/api/v1/ops/jobs/dead-letter")).json()
    item = next(i for i in masked["items"] if i["id"] == str(restricted))
    assert item["document_title"] == "Document restreint"
    assert "confidentiel" not in (item["error"] or "")

    unknown = await admin_client.get("/api/v1/ops/jobs/dead-letter", params={"project": "inconnu"})
    assert unknown.status_code == 404
