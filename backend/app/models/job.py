"""Ingestion job queue (Postgres, ``SELECT … FOR UPDATE SKIP LOCKED``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
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
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[JobKind] = mapped_column(StrEnumType(JobKind), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        StrEnumType(JobStatus), nullable=False, default=JobStatus.queued, server_default=text("'queued'")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``[{"name", "status", "started_at", "duration_ms", "detail"}]`` — see ``app.ingestion.queue``.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
