"""Job queue (Postgres, ``SELECT … FOR UPDATE SKIP LOCKED``), worker heartbeats and scheduled tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin, utcnow
from app.enums import JobKind, JobStatus
from app.models._types import StrEnumType, enum_check


class IngestionJob(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        enum_check("kind", JobKind),
        enum_check("status", JobStatus),
        Index("ix_ingestion_jobs_status_run_after", "status", "run_after"),
        Index("ix_ingestion_jobs_project_id_created_at", "project_id", "created_at"),
        Index("ix_ingestion_jobs_document_id", "document_id"),
        # Fair claim: head of each project's queue (DISTINCT ON project_id ORDER BY priority, run_after).
        Index(
            "ix_ingestion_jobs_queued_fair",
            "project_id",
            text("priority DESC"),
            "run_after",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
    )

    #: ``NULL`` for platform-wide jobs (global reindex).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[JobKind] = mapped_column(StrEnumType(JobKind), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        StrEnumType(JobStatus), nullable=False, default=JobStatus.queued, server_default=text("'queued'")
    )
    #: Higher runs first (``0`` default; interactive uploads may use ``10``, bulk rebuilds ``-10``).
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
    #: Times the job was found running with an expired lock (worker crash / OOM kill): poison-pill detection.
    crash_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``[{"name", "status", "started_at", "duration_ms", "detail"}]`` — see ``app.ingestion.queue``.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Refreshed by the worker heartbeat while the job runs (stale-lock reaper threshold).
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Set by ``POST …/jobs/{id}/cancel`` on a running job; the worker stops it at its next heartbeat.
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: W3C ``traceparent`` of the request that enqueued the job (worker span is linked to it).
    trace_parent: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkerHeartbeat(Base):
    """One row per worker process, refreshed every ``ORBIT_WORKER_HEARTBEAT_SECONDS``."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(Text, primary_key=True)
    hostname: Mapped[str] = mapped_column(Text, nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False, default="")
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    in_flight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    stopping: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class ScheduledTask(Base):
    """Last run of a cluster-wide singleton task (maintenance, retention, drift check…)."""

    __tablename__ = "scheduled_tasks"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ``ok`` | ``failed`` | ``skipped`` | ``running``
    last_status: Mapped[str] = mapped_column(Text, nullable=False, default="never", server_default=text("'never'"))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    holder: Mapped[str | None] = mapped_column(Text, nullable=True)
