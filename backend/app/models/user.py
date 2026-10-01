"""Users (platform identities)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.models._types import range_check

DEFAULT_AVATAR_COLOR = "#4f46e5"


class User(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        range_check("clearance", 0, 3),
        Index("uq_users_email", "email", unique=True),
        Index(
            "uq_users_oidc_subject",
            "oidc_subject",
            unique=True,
            postgresql_where=text("oidc_subject IS NOT NULL"),
        ),
        CheckConstraint("auth_provider IN ('local', 'oidc')", name="auth_provider"),
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
    # --- Lifecycle & authentication (docs/PRODUCTION.md, identity workstream) ---
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: ``local`` (password, optional TOTP) or ``oidc`` (SSO, JIT-provisioned).
    auth_provider: Mapped[str] = mapped_column(
        Text, nullable=False, default="local", server_default=text("'local'")
    )
    oidc_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    #: TOTP secret, encrypted (AES-256-GCM, see app/identity/secretbox.py).
    mfa_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Secret being enrolled (``/account/mfa/setup``), promoted by ``/account/mfa/enable``.
    mfa_pending_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: SHA-256 hashes of the unused recovery codes.
    mfa_recovery_codes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: Last accepted TOTP time step (replay protection).
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
