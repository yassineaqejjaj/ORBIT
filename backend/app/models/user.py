"""Users (platform identities)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, SmallInteger, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.models._types import range_check
from app.models.workspace import forbid_workspace_change, workspace_id_column

DEFAULT_AVATAR_COLOR = "#4f46e5"


class User(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        range_check("clearance", 0, 3),
        Index("uq_users_email", "email", unique=True),
        Index("ix_users_workspace_id", "workspace_id"),
        # At most one break-glass account (ADR 001 §8): an index on a constant, restricted to the flagged row.
        Index("uq_users_break_glass", "is_break_glass", unique=True, postgresql_where=text("is_break_glass")),
        CheckConstraint(
            "NOT is_break_glass OR (is_admin AND NOT password_login_disabled AND NOT sso_required)",
            name="break_glass_rules",
        ),
    )

    #: Space of the account (ADR 001 §5). Immutable; a request's workspace comes from the validated identity.
    workspace_id: Mapped[uuid.UUID] = workspace_id_column()

    email: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    clearance: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default=text("1"))
    avatar_color: Mapped[str] = mapped_column(
        Text, nullable=False, default=DEFAULT_AVATAR_COLOR, server_default=text(f"'{DEFAULT_AVATAR_COLOR}'")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ADR 001 §8 phase 3 (NOV-113): password login refused for this account (it signs in through the IdP).
    password_login_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    #: Policy flag: this account must use SSO (also refuses the password); needs a linked identity to be set.
    sso_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    #: The administrator account outside SSO (password kept offline). At most one; always an administrator.
    is_break_glass: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    #: Set when the user finishes or skips the first-login onboarding tour; NULL means "not onboarded yet".
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


forbid_workspace_change(User)
