"""Models of the triage & change-feed product features (docs/FEATURES.md F1/F2).

* ``change_events`` — append-only feed of notable changes, written with the action that caused them;
  each row carries the classification and ACL of its target so it can be filtered by rights.
* ``subscriptions`` — per-member digest preferences.
* ``webhooks`` / ``webhook_deliveries`` — outgoing signed notifications (delivered by the job queue).
* ``conflict_resolutions`` — arbitration of ``contradicts`` relations (resolved or dismissed). The
  relation id is kept without foreign key: a supersession deletes the ``contradicts`` edge.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    REAL,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin
from app.models._types import range_check
from app.models.source import default_acl

__all__ = ["ChangeEvent", "ConflictResolution", "Subscription", "Webhook", "WebhookDelivery"]


class ChangeEvent(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "change_events"
    __table_args__ = (
        range_check("classification", 0, 3),
        Index("ix_change_events_project_id_created_at", "project_id", text("created_at DESC")),
        Index("ix_change_events_project_id_type", "project_id", "type"),
        Index("ix_change_events_target_id", "target_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    target_type: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default=text("1")
    )
    acl_principals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=default_acl, server_default=text("ARRAY['project:*']::text[]")
    )
    actor_label: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class Subscription(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("digest IN ('off', 'daily', 'weekly')", name="digest"),
        Index("uq_subscriptions_project_id_user_id", "project_id", "user_id", unique=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    digest: Mapped[str] = mapped_column(Text, nullable=False, default="off", server_default=text("'off'"))
    types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    last_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Webhook(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "webhooks"
    __table_args__ = (Index("ix_webhooks_project_id", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    #: Fernet token of the signing secret (``settings.encryption_key``).
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hint: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class WebhookDelivery(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'skipped')", name="status"),
        Index("ix_webhook_deliveries_webhook_id_created_at", "webhook_id", text("created_at DESC")),
    )

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    change_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_events.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(REAL, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConflictResolution(CreatedAtMixin, Base):
    __tablename__ = "conflict_resolutions"
    __table_args__ = (
        CheckConstraint("status IN ('resolved', 'dismissed')", name="status"),
        Index("ix_conflict_resolutions_project_id_created_at", "project_id", text("created_at DESC")),
    )

    #: Id of the original ``contradicts`` relation (= ``Conflict.id``).
    relation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    a_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    b_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    winner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    similarity: Mapped[float] = mapped_column(REAL, nullable=False, default=0.0, server_default=text("0"))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_by_label: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
