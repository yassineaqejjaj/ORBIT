"""User management helpers (creation, lookup, password changes, bootstrap administrator)."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LEGACY_BOOTSTRAP_PASSWORD, settings
from app.db import utcnow
from app.identity.passwords import generate_password
from app.models import User
from app.schemas.common import normalize_email
from app.security import hash_password

logger = logging.getLogger("orbit.users")

AVATAR_PALETTE: tuple[str, ...] = (
    "#4f46e5",
    "#0891b2",
    "#059669",
    "#d97706",
    "#dc2626",
    "#7c3aed",
    "#db2777",
    "#2563eb",
    "#0d9488",
    "#ea580c",
)


def avatar_color_for(email: str) -> str:
    digest = hashlib.sha256(email.lower().encode()).digest()
    return AVATAR_PALETTE[digest[0] % len(AVATAR_PALETTE)]


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.strip().lower()))


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    password: str,
    clearance: int = 1,
    is_admin: bool = False,
    must_change_password: bool = False,
) -> User:
    """Create (and flush) a user. The e-mail must already be unique (caller checks, DB enforces).

    The password policy is enforced by the API layer (``app.identity.passwords``), not here, so that
    fixtures and the demo seed can create accounts directly.
    """
    normalized = normalize_email(email)
    user = User(
        email=normalized,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        clearance=clearance,
        is_admin=is_admin,
        avatar_color=avatar_color_for(normalized),
        must_change_password=must_change_password,
        password_changed_at=utcnow(),
    )
    session.add(user)
    await session.flush()
    return user


async def count_admins(session: AsyncSession) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True))) or 0
    )


def set_password(user: User, password: str, *, must_change: bool = False) -> None:
    """Replace the password hash (invalidates every JWT through the password fingerprint)."""
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    user.must_change_password = must_change


async def ensure_bootstrap_admin(session: AsyncSession) -> User | None:
    """Create the bootstrap administrator (clearance C3) when the database has no user at all.

    Without ``ORBIT_BOOTSTRAP_ADMIN_PASSWORD`` a random one-time password is generated, written **once**
    to the logs, and must be changed at the first login (``must_change_password``).
    """
    existing = await session.scalar(select(func.count()).select_from(User))
    if existing:
        return None
    configured = settings.bootstrap_admin_password
    password = configured or generate_password(24)
    user = await create_user(
        session,
        email=settings.bootstrap_admin_email,
        full_name=settings.bootstrap_admin_name,
        password=password,
        clearance=3,
        is_admin=True,
        must_change_password=not configured,
    )
    await session.commit()
    if configured:
        if configured == LEGACY_BOOTSTRAP_PASSWORD:
            logger.warning(
                "Bootstrap administrator %s created with the historical default password: change it now "
                "(refused when ORBIT_ENV=production).",
                user.email,
            )
        else:
            logger.warning(
                "Bootstrap administrator %s created with ORBIT_BOOTSTRAP_ADMIN_PASSWORD.", user.email
            )
    else:
        logger.warning(
            "Bootstrap administrator %s created. One-time password (shown once, must be changed at the "
            "first login): %s",
            user.email,
            password,
        )
    return user
