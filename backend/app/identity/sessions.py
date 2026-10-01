"""Server-side user sessions (docs/PRODUCTION.md §0 « Sessions »).

Every session JWT carries a ``sid`` claim pointing to a ``user_sessions`` row. A request is only
authenticated when that row exists, is not revoked, has not reached its absolute expiry
(``SESSION_ABSOLUTE_HOURS``) and was seen less than ``SESSION_IDLE_MINUTES`` ago. ``last_seen_at``
is refreshed at most once per :data:`TOUCH_RESOLUTION` (sliding idle timeout without a write per call).

Sessions are revoked on logout, password change/reset, deactivation, erasure and on demand
(``DELETE /account/sessions/{id}``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.config import settings
from app.db import utcnow
from app.identity.netutil import client_ip
from app.models import User
from app.models.identity import UserSession
from app.security import create_access_token

#: ``last_seen_at`` is written at most once per interval (idle timeout precision).
TOUCH_RESOLUTION = timedelta(seconds=60)
USER_AGENT_MAX_LENGTH = 512


class AuthMethod(StrEnum):
    password = "password"
    mfa = "mfa"
    oidc = "oidc"
    invitation = "invitation"
    password_change = "password_change"


class RevokeReason(StrEnum):
    logout = "logout"
    user_revoked = "user_revoked"
    password_changed = "password_changed"
    password_reset = "password_reset"
    deactivated = "deactivated"
    idle_timeout = "idle_timeout"
    admin = "admin"
    erased = "erased"
    mfa_changed = "mfa_changed"


class SessionInvalid(Exception):
    """The session referenced by a JWT cannot authenticate a request (French message for the client)."""


@dataclass(frozen=True, slots=True)
class IssuedSession:
    row: UserSession
    token: str


async def create_session(
    db: AsyncSession, user: User, *, conn: HTTPConnection | None, method: AuthMethod
) -> IssuedSession:
    """Insert a session row (flushed, caller commits) and mint its JWT (``sid`` + password fingerprint)."""
    now = utcnow()
    user_agent = conn.headers.get("user-agent", "")[:USER_AGENT_MAX_LENGTH] if conn is not None else ""
    row = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        ip=client_ip(conn) if conn is not None else None,
        user_agent=user_agent or None,
        auth_method=method.value,
    )
    db.add(row)
    await db.flush()
    token = create_access_token(
        user.id, session_id=row.id, password_hash=user.password_hash, ttl_seconds=settings.session_ttl_seconds
    )
    return IssuedSession(row=row, token=token)


def _idle_deadline(row: UserSession) -> datetime:
    return row.last_seen_at + timedelta(seconds=settings.session_idle_seconds)


def is_active(row: UserSession, *, now: datetime | None = None) -> bool:
    current = now or utcnow()
    return row.revoked_at is None and row.expires_at > current and _idle_deadline(row) > current


async def validate_session(db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID) -> UserSession:
    """Return the live session row or raise :class:`SessionInvalid`; slides the idle deadline."""
    row = await db.get(UserSession, session_id)
    if row is None or row.user_id != user_id:
        raise SessionInvalid("Session invalide")
    now = utcnow()
    if row.revoked_at is not None:
        raise SessionInvalid("Session révoquée")
    if row.expires_at <= now:
        raise SessionInvalid("Session expirée")
    if _idle_deadline(row) <= now:
        await db.execute(
            update(UserSession)
            .where(UserSession.id == row.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=RevokeReason.idle_timeout.value)
        )
        await db.commit()
        raise SessionInvalid("Session expirée après inactivité")
    if now - row.last_seen_at >= TOUCH_RESOLUTION:
        await db.execute(update(UserSession).where(UserSession.id == row.id).values(last_seen_at=now))
        await db.commit()
        row.last_seen_at = now
    return row


async def revoke_session(db: AsyncSession, session_id: uuid.UUID, reason: RevokeReason) -> bool:
    """Revoke one session (caller commits). Returns ``False`` when it was already revoked or unknown."""
    result = await db.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason.value)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def revoke_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, reason: RevokeReason, *, keep: uuid.UUID | None = None
) -> int:
    """Revoke every live session of a user except ``keep`` (caller commits). Returns the count."""
    statement = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoked_reason=reason.value)
    )
    if keep is not None:
        statement = statement.where(UserSession.id != keep)
    result = await db.execute(statement)
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def list_active_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[UserSession]:
    now = utcnow()
    rows = await db.scalars(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            UserSession.last_seen_at > now - timedelta(seconds=settings.session_idle_seconds),
        )
        .order_by(UserSession.last_seen_at.desc())
    )
    return list(rows)
