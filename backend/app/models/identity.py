"""Models of the `identity` workstream (production readiness, see docs/PRODUCTION.md).

* ``user_sessions`` — server-side sessions (JWT ``sid``): revocation, idle and absolute expiry;
* ``agent_delegations`` — a user allows an agent to act on their behalf (``on_behalf_of``);
* ``user_invitations`` — admin invitations (single-use token, only its hash is stored).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.models._types import range_check

__all__ = ["AgentDelegation", "UserInvitation", "UserSession"]


class UserSession(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_id", "user_id"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``password`` | ``mfa`` | ``oidc`` | ``invitation`` | ``password_change``.
    auth_method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'password'"))


class AgentDelegation(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "agent_delegations"
    __table_args__ = (
        range_check("max_classification", 0, 3, nullable=True),
        Index("ix_agent_delegations_project_id", "project_id"),
        Index("ix_agent_delegations_user_id", "user_id"),
        Index(
            "uq_agent_delegations_active",
            "agent_id",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    max_classification: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserInvitation(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "user_invitations"
    __table_args__ = (
        range_check("clearance", 0, 3),
        Index("uq_user_invitations_token_hash", "token_hash", unique=True),
    )

    email: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    clearance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
