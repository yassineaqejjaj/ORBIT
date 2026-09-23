"""Short-term memory buffer in Valkey (ARCHITECTURE §8).

Key layout: ``orbit:session:{project_id}:{session_id}`` (list of JSON turns
``{"role", "content", "at", "agent_id"}``) with a TTL of ``settings.short_term_ttl_hours`` of the
project, refreshed on each turn; ``orbit:sessions:{project_id}`` (sorted set, score = last update
timestamp) indexes the sessions of a project.

The Valkey client helpers are implemented; the buffer operations are the memory teammate's contract.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import redis.asyncio as redis

from app.config import settings
from app.enums import TurnRole

_client: redis.Redis | None = None


def get_valkey() -> redis.Redis:
    """Process-wide Valkey client (``ORBIT_VALKEY_URL``, responses decoded as ``str``)."""
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.valkey_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=3,
            health_check_interval=30,
        )
    return _client


async def close_valkey() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def session_key(project_id: uuid.UUID | str, session_id: str) -> str:
    return f"orbit:session:{project_id}:{session_id}"


def sessions_index_key(project_id: uuid.UUID | str) -> str:
    return f"orbit:sessions:{project_id}"


@dataclass(slots=True)
class Turn:
    role: TurnRole
    content: str
    at: datetime
    agent_id: uuid.UUID | None = None


@dataclass(slots=True)
class SessionInfo:
    session_id: str
    turns: int
    updated_at: datetime
    expires_at: datetime | None


async def append_turn(
    project_id: uuid.UUID,
    session_id: str,
    role: TurnRole,
    content: str,
    *,
    ttl_hours: int,
    agent_id: uuid.UUID | None = None,
) -> tuple[int, datetime]:
    """Append a turn and refresh the TTL. Returns ``(turn_count, expires_at)``."""
    raise NotImplementedError("Mémoire court terme non implémentée")


async def get_turns(project_id: uuid.UUID, session_id: str, *, limit: int | None = None) -> list[Turn]:
    """Turns of a session in chronological order (the most recent ``limit`` when given)."""
    raise NotImplementedError


async def get_expiry(project_id: uuid.UUID, session_id: str) -> datetime | None:
    raise NotImplementedError


async def list_sessions(project_id: uuid.UUID) -> list[SessionInfo]:
    """Live sessions of the project, most recently updated first (expired entries pruned)."""
    raise NotImplementedError


async def clear_session(project_id: uuid.UUID, session_id: str) -> None:
    raise NotImplementedError


async def purge_matching(project_id: uuid.UUID, needle: str) -> int:
    """Remove turns containing ``needle`` (selective forgetting propagation). Returns removed count."""
    raise NotImplementedError
