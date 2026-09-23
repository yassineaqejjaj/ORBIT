"""AI agents (API-key identities bound to a project)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.enums import AgentKind
from app.models._types import StrEnumType, enum_check, range_check


class Agent(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        enum_check("kind", AgentKind),
        range_check("clearance", 0, 3),
        Index("uq_agents_api_key_prefix", "api_key_prefix", unique=True),
        Index("ix_agents_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[AgentKind] = mapped_column(StrEnumType(AgentKind), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    clearance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default=text("1"))
    api_key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
