"""Compliance workstream tables (docs/PRODUCTION.md §3 « Conformité », migration ``0003``).

* ``compliance_tasks``   — transactional outbox of erasure side effects (OpenSearch, Valkey, object store,
  derived copies). A task row is written in the same transaction as the erasure decision and processed
  (with retries and backoff) until every derived store confirmed the purge. No foreign key: a project
  purge task outlives the project it deletes and doubles as the deletion certificate.
* ``compliance_settings`` — small key/value store (retention overrides, last retention run, per-user
  consent for personal memory created by agents).
* ``audit_checkpoints``   — head of the audit hash chain recorded when the retention purge deletes the
  oldest audit entries, so that the remaining chain stays verifiable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin, utcnow
from app.models._types import StrEnumType, enum_check


class ComplianceTaskKind(StrEnum):
    #: Purge forgotten memory items from the memory index, session buffers and derived copies.
    memory_purge = "memory_purge"
    #: Scrub derived copies (contexts, decisions, snapshots, audit summaries) of a forgotten document.
    document_scrub = "document_scrub"
    #: GDPR art. 17 erasure of a user (pseudonymisation + purge of personal data).
    user_erasure = "user_erasure"
    #: Complete purge of a deleted project (index, objects, Valkey, rows).
    project_purge = "project_purge"


class ComplianceTaskStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class ComplianceTask(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "compliance_tasks"
    __table_args__ = (
        enum_check("kind", ComplianceTaskKind),
        enum_check("status", ComplianceTaskStatus),
        Index("ix_compliance_tasks_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_compliance_tasks_project_id", "project_id"),
    )

    kind: Mapped[ComplianceTaskKind] = mapped_column(StrEnumType(ComplianceTaskKind), nullable=False)
    status: Mapped[ComplianceTaskStatus] = mapped_column(
        StrEnumType(ComplianceTaskStatus),
        nullable=False,
        default=ComplianceTaskStatus.pending,
        server_default=text("'pending'"),
    )
    #: Project concerned (no foreign key on purpose, see module docstring).
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: Identifiers only — never the erased content itself.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default=text("12"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Counters of what was purged (deletion certificate).
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplianceSetting(Base):
    __tablename__ = "compliance_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, server_default=text("now()")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class AuditCheckpoint(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_checkpoints"

    #: ``seq`` / ``hash`` of the last audit entry deleted by the purge (new chain anchor).
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    hash: Mapped[str] = mapped_column(Text, nullable=False)
    purged_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "AuditCheckpoint",
    "ComplianceSetting",
    "ComplianceTask",
    "ComplianceTaskKind",
    "ComplianceTaskStatus",
]
