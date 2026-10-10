"""Users (platform identities)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, SmallInteger, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.models._types import range_check

DEFAULT_AVATAR_COLOR = "#4f46e5"


class User(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        range_check("clearance", 0, 3),
        Index("uq_users_email", "email", unique=True),
    )

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
    #: Set when the user finishes or skips the first-login onboarding tour; NULL means "not onboarded yet".
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
