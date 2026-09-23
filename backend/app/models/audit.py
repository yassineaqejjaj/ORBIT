"""Audit trail of every significant action (ARCHITECTURE §12)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.enums import ActorType
from app.models._types import StrEnumType, enum_check


class AuditLog(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        enum_check("actor_type", ActorType),
        Index("ix_audit_log_project_id_created_at", "project_id", text("created_at DESC")),
        Index("ix_audit_log_action", "action"),
    )

    #: ``NULL`` for platform-level events (login, user administration).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
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
