"""Models of the `connector` product feature (docs/FEATURES.md F5).

* ``connectors`` — one SharePoint/OneDrive, Confluence or Jira connection of a project: non-secret
  configuration (``config``), Fernet-encrypted secret (``secret_ciphertext``, key ``ORBIT_ENCRYPTION_KEY``),
  schedule, incremental ``cursor`` and the ORBIT ``source`` the synced documents belong to.
* ``connector_runs`` — one synchronisation (manual, scheduled or initial) with its statistics and
  live progress (polled by the onboarding wizard).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    REAL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin
from app.models._types import range_check

__all__ = [
    "CONNECTOR_RUN_STATUSES",
    "CONNECTOR_STATUSES",
    "CONNECTOR_TYPES",
    "Connector",
    "ConnectorRun",
]

CONNECTOR_TYPES = ("sharepoint", "confluence", "jira", "mcp")
#: ``idle`` never synced, ``syncing`` run queued/running, ``ok`` last run fine, ``error`` last run failed,
#: ``paused`` scheduled syncs disabled (manual syncs still allowed).
CONNECTOR_STATUSES = ("idle", "syncing", "ok", "error", "paused")
#: ``partial``: finished but some items failed.
CONNECTOR_RUN_STATUSES = ("queued", "running", "succeeded", "partial", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Connector(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (
        CheckConstraint(_in("type", CONNECTOR_TYPES), name="type"),
        CheckConstraint(_in("status", CONNECTOR_STATUSES), name="status"),
        range_check("default_classification", 0, 3),
        CheckConstraint("schedule_minutes >= 0", name="schedule_minutes_positive"),
        Index("ix_connectors_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Non-secret settings (base URL, tenant/client id, e-mail, scope: sites/drives, spaces, JQL…).
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    #: Fernet token of the secret (client secret, API token or PAT). Never returned by the API.
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_hint: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    schedule_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default=text("60")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="idle", server_default=text("'idle'"))
    default_classification: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default=text("1")
    )
    #: « Restreindre aux éditeurs » : synced documents get ``['role:editor']`` instead of ``['project:*']``.
    restrict_to_editors: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default=text("false")
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Incremental state (Graph delta links per drive, last ``lastmodified`` / ``updated`` seen…).
    cursor: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ConnectorRun(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "connector_runs"
    __table_args__ = (
        CheckConstraint(_in("status", CONNECTOR_RUN_STATUSES), name="status"),
        CheckConstraint(_in("trigger", ("manual", "schedule", "initial")), name="trigger"),
        Index("ix_connector_runs_connector_id_created_at", "connector_id", text("created_at DESC")),
    )

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trigger: Mapped[str] = mapped_column(
        Text, nullable=False, default="manual", server_default=text("'manual'")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="queued", server_default=text("'queued'")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(REAL, nullable=True)
    fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    forgotten: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    #: Live progress shown by the wizard: ``{"phase", "message", "current"}``.
    progress: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    #: First item errors (``[{"item", "error"}]``, capped).
    error_samples: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
