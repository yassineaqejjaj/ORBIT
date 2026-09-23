"""Database plumbing: async engine, session factory, declarative ``Base`` and FastAPI dependency.

Transactions are explicit: routers and services call ``await session.commit()`` themselves.
Sessions use ``expire_on_commit=False`` so ORM objects stay readable after a commit (no lazy
loads in async code).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Timezone-aware current UTC time (used for Python-side column defaults)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def __repr__(self) -> str:
        ident = getattr(self, "id", None)
        return f"<{type(self).__name__} id={ident}>"


# --- Reusable column mixins -----------------------------------------------------------------------


class UUIDPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, sort_order=-100
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()"), sort_order=100
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=text("now()"),
        sort_order=101,
    )


# --- Engine & sessions ----------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs(url: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
    if not url.startswith("sqlite"):
        kwargs.update(
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_recycle=1800,
        )
    return kwargs


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine (created lazily from ``ORBIT_DATABASE_URL``)."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=True)
    return _sessionmaker


def configure_engine(url: str) -> AsyncEngine:
    """Replace the global engine (tests, scripts). Existing engine must be disposed by the caller."""
    global _engine, _sessionmaker
    _engine = create_async_engine(url, **_engine_kwargs(url))
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=True)
    return _engine


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session. Uncommitted work is rolled back when the request ends."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope for scripts/worker: commits on success, rolls back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
