"""Audit trail of every significant action (ARCHITECTURE §12, docs/PRODUCTION.md « Audit »).

The table is append-only and hash-chained (migration ``0003``): a ``BEFORE INSERT`` trigger takes a
transaction-scoped advisory lock, assigns a gapless ``seq`` and computes ``content_hash`` (SHA-256 of a
canonical JSON array of the row) and ``hash = sha256(prev_hash:seq:content_hash)``. ``UPDATE`` and
``DELETE`` are refused by a trigger, except through the ``orbit_audit_redact`` (GDPR pseudonymisation,
sets ``redacted_at``) and ``orbit_audit_purge`` (retention, records an ``audit_checkpoints`` anchor)
SECURITY DEFINER functions, and the ``project_id → NULL`` update of the project foreign key.
``project_ref`` keeps the original project id (hashed) once the project is deleted.
"""

from __future__ import annotations

import uuid
from typing import Any

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, FetchedValue, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.enums import ActorType
from app.models._types import StrEnumType, enum_check


class AuditLog(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_log"
    #: Fetch the trigger-computed chain columns with ``RETURNING`` (no lazy load in async code).
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        enum_check("actor_type", ActorType),
        Index("ix_audit_log_project_id_created_at", "project_id", text("created_at DESC")),
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_seq", "seq", unique=True),
        Index("ix_audit_log_actor_action_target", "actor_id", "action", "target_id", text("created_at DESC")),
    )

    #: ``NULL`` for platform-level events (login, user administration).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[ActorType] = mapped_column(StrEnumType(ActorType), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_label: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    #: Free-form identifier (uuid, snapshot ``name@vN``, ...).
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # --- Hash chain (computed by the database trigger; never written by the application) ----------
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=FetchedValue())
    prev_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=FetchedValue())
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=FetchedValue())
    hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=FetchedValue())
    #: Immutable copy of ``project_id`` (kept when the project is deleted, part of the hash).
    project_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, server_default=FetchedValue()
    )
    #: Set when personal data of the entry was pseudonymised (content no longer matches its hash).
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
