"""User management helpers (creation, lookup, bootstrap administrator)."""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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
) -> User:
    """Create (and flush) a user. The e-mail must already be unique (caller checks, DB enforces)."""
    normalized = normalize_email(email)
    user = User(
        email=normalized,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        clearance=clearance,
        is_admin=is_admin,
        avatar_color=avatar_color_for(normalized),
    )
    session.add(user)
    await session.flush()
    return user


async def count_admins(session: AsyncSession) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True))) or 0
    )


async def ensure_bootstrap_admin(session: AsyncSession) -> User | None:
    """Create the bootstrap administrator when the database has no user at all (clearance C3)."""
    existing = await session.scalar(select(func.count()).select_from(User))
    if existing:
        return None
    user = await create_user(
        session,
        email=settings.bootstrap_admin_email,
        full_name=settings.bootstrap_admin_name,
        password=settings.bootstrap_admin_password,
        clearance=3,
        is_admin=True,
    )
    await session.commit()
    logger.warning(
        "Bootstrap administrator created (%s). Change its password after the first login.", user.email
    )
    return user
