"""Tombstones for selective forgetting (propagated to index, derived memory, Valkey, snapshots)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.enums import TombstoneTarget
from app.models._types import StrEnumType, enum_check


class Tombstone(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "tombstones"
    __table_args__ = (
        enum_check("target_type", TombstoneTarget),
        Index("ix_tombstones_project_id_target_type_target_id", "project_id", "target_type", "target_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    target_type: Mapped[TombstoneTarget] = mapped_column(StrEnumType(TombstoneTarget), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    propagated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
