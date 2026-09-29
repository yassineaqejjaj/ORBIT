"""Short-term memory buffer in Valkey (ARCHITECTURE §8).

Key layout: ``orbit:session:{project_id}:{session_id}`` (list of JSON turns
``{"role", "content", "at", "agent_id"}``) with a TTL of ``settings.short_term_ttl_hours`` of the
project, refreshed on each turn; ``orbit:sessions:{project_id}`` (sorted set, score = last update
timestamp) indexes the sessions of a project.

Every write refreshes the TTL of the session list and of the project index. Expired sessions vanish
from Valkey on their own; :func:`list_sessions` prunes their stale index entries.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import redis.asyncio as redis

from app.config import settings
from app.enums import TurnRole
from app.memory.conflicts import fold

logger = logging.getLogger("orbit.memory.short_term")

#: Hard cap on buffered turns per session (oldest turns are trimmed).
MAX_TURNS_PER_SESSION = 500
#: Needles shorter than this are ignored by :func:`purge_matching` (avoids mass deletion).
MIN_PURGE_NEEDLE_LENGTH = 6
#: A session without new turn for this long is considered idle and gets consolidated.
IDLE_SESSION_HOURS = 12

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


def idle_threshold(ttl_hours: int) -> timedelta:
    """Idle delay after which a session is closed by consolidation (before its TTL expires)."""
    return timedelta(hours=min(IDLE_SESSION_HOURS, max(1.0, ttl_hours * 0.5)))


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
    now = datetime.now(UTC)
    ttl_seconds = max(60, int(ttl_hours * 3600))
    turn = {
        "role": TurnRole(role).value,
        "content": content,
        "at": now.isoformat(),
        "agent_id": str(agent_id) if agent_id else None,
    }
    key = session_key(project_id, session_id)
    index = sessions_index_key(project_id)
    async with get_valkey().pipeline(transaction=True) as pipe:
        pipe.rpush(key, json.dumps(turn, ensure_ascii=False))
        pipe.ltrim(key, -MAX_TURNS_PER_SESSION, -1)
        pipe.expire(key, ttl_seconds)
        pipe.llen(key)
        pipe.zadd(index, {session_id: now.timestamp()})
        pipe.expire(index, ttl_seconds, gt=True)
        pipe.expire(index, ttl_seconds, nx=True)
        results = await pipe.execute()
    count = int(results[3])
    return count, now + timedelta(seconds=ttl_seconds)


def _parse_turn(raw: str) -> Turn | None:
    try:
        data: dict[str, Any] = json.loads(raw)
        at = datetime.fromisoformat(str(data["at"]))
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        agent_raw = data.get("agent_id")
        return Turn(
            role=TurnRole(data.get("role", TurnRole.agent)),
            content=str(data.get("content", "")),
            at=at,
            agent_id=uuid.UUID(str(agent_raw)) if agent_raw else None,
        )
    except (ValueError, KeyError, TypeError):
        logger.warning("Ignoring malformed session turn in Valkey")
        return None


async def get_turns(project_id: uuid.UUID, session_id: str, *, limit: int | None = None) -> list[Turn]:
    """Turns of a session in chronological order (the most recent ``limit`` when given)."""
    start = -limit if limit and limit > 0 else 0
    raw_turns = cast(list[str], await get_valkey().lrange(session_key(project_id, session_id), start, -1))
    turns = [_parse_turn(raw) for raw in raw_turns]
    return [turn for turn in turns if turn is not None]


def _expiry_from_pttl(pttl: int | None, now: datetime) -> datetime | None:
    if pttl is None or pttl < 0:
        return None
    return now + timedelta(milliseconds=int(pttl))


async def get_expiry(project_id: uuid.UUID, session_id: str) -> datetime | None:
    pttl = await get_valkey().pttl(session_key(project_id, session_id))
    return _expiry_from_pttl(pttl, datetime.now(UTC))


async def list_sessions(project_id: uuid.UUID) -> list[SessionInfo]:
    """Live sessions of the project, most recently updated first (expired entries pruned)."""
    client = get_valkey()
    index = sessions_index_key(project_id)
    entries = cast(list[tuple[str, float]], await client.zrevrange(index, 0, -1, withscores=True))
    if not entries:
        return []
    async with client.pipeline(transaction=False) as pipe:
        for session_id, _score in entries:
            key = session_key(project_id, session_id)
            pipe.llen(key)
            pipe.pttl(key)
        results = await pipe.execute()
    now = datetime.now(UTC)
    sessions: list[SessionInfo] = []
    stale: list[str] = []
    for position, (session_id, score) in enumerate(entries):
        length, pttl = int(results[2 * position]), results[2 * position + 1]
        if length <= 0 or pttl == -2:
            stale.append(session_id)
            continue
        sessions.append(
            SessionInfo(
                session_id=session_id,
                turns=length,
                updated_at=datetime.fromtimestamp(float(score), UTC),
                expires_at=_expiry_from_pttl(pttl, now),
            )
        )
    if stale:
        await client.zrem(index, *stale)
    return sessions


async def clear_session(project_id: uuid.UUID, session_id: str) -> None:
    async with get_valkey().pipeline(transaction=True) as pipe:
        pipe.delete(session_key(project_id, session_id))
        pipe.zrem(sessions_index_key(project_id), session_id)
        await pipe.execute()


async def purge_matching(project_id: uuid.UUID, needle: str) -> int:
    """Remove turns containing ``needle`` (selective forgetting propagation). Returns removed count.

    Matching is case- and accent-insensitive. Needles shorter than ``MIN_PURGE_NEEDLE_LENGTH``
    characters are ignored. The TTL of each session is preserved (``LREM`` keeps it).
    """
    folded_needle = fold(" ".join((needle or "").split()))
    if len(folded_needle) < MIN_PURGE_NEEDLE_LENGTH:
        return 0
    client = get_valkey()
    session_ids = cast(list[str], await client.zrange(sessions_index_key(project_id), 0, -1))
    removed = 0
    for session_id in session_ids:
        key = session_key(project_id, session_id)
        raw_turns = cast(list[str], await client.lrange(key, 0, -1))
        matching: set[str] = set()
        for raw in raw_turns:
            turn = _parse_turn(raw)
            content = turn.content if turn is not None else raw
            if folded_needle in fold(" ".join(content.split())):
                matching.add(raw)
        for raw in matching:
            removed += int(await client.lrem(key, 0, raw))
        if matching and not await client.exists(key):
            await client.zrem(sessions_index_key(project_id), session_id)
    return removed
