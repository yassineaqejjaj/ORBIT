"""Live event bus on Valkey pub/sub (works with several API/worker processes).

Events are **queued on the SQLAlchemy session and published after the commit** (so a client that
refetches on an event sees the data); a rollback drops them. A message carries ids and counters only,
plus the classification / ACL used to filter it per subscriber. A short per-project log allows the
``Last-Event-ID`` resume. When Valkey is down publishing is a no-op (clients fall back to polling).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import orjson
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.observability.metrics import LIVE_EVENTS_PUBLISHED_TOTAL

logger = logging.getLogger("orbit.live")

KINDS = ("context.served", "ingestion.updated", "memory.changed", "snapshot.created")
LOG_SIZE = 200
LOG_TTL_SECONDS = 900
_INFO_KEY = "orbit_live_events"
_tasks: set[asyncio.Task[None]] = set()


def channel(project_id: Any) -> str:
    return f"orbit:live:{project_id}"


def _log_key(project_id: Any) -> str:
    return f"orbit:live:log:{project_id}"


def _seq_key(project_id: Any) -> str:
    return f"orbit:live:seq:{project_id}"


def queue(
    session: Any,
    project_id: Any,
    kind: str,
    ids: dict[str, Any] | None = None,
    *,
    classification: int = 0,
    acl: list[str] | None = None,
) -> None:
    """Publish ``kind`` once the session's transaction commits (``session``: async or sync)."""
    sync = getattr(session, "sync_session", session)
    sync.info.setdefault(_INFO_KEY, []).append(
        (str(project_id), kind, {k: v for k, v in (ids or {}).items() if v is not None}, classification, acl)
    )


async def publish(
    project_id: Any,
    kind: str,
    ids: dict[str, Any] | None = None,
    *,
    classification: int = 0,
    acl: list[str] | None = None,
) -> int | None:
    """Publish now; returns the event id or ``None`` when the bus is unavailable."""
    from app.memory.short_term import get_valkey

    try:
        client = get_valkey()
        seq = int(await client.incr(_seq_key(project_id)))
        message = orjson.dumps(
            {
                "id": seq,
                "kind": kind,
                "data": ids or {},
                "classification": classification,
                "acl": acl,
                "ts": time.time(),
            }
        ).decode()
        async with client.pipeline(transaction=False) as pipe:
            pipe.lpush(_log_key(project_id), message)
            pipe.ltrim(_log_key(project_id), 0, LOG_SIZE - 1)
            pipe.expire(_log_key(project_id), LOG_TTL_SECONDS)
            pipe.expire(_seq_key(project_id), 86_400)
            pipe.publish(channel(project_id), message)
            await pipe.execute()
        LIVE_EVENTS_PUBLISHED_TOTAL.labels(kind=kind).inc()
        return seq
    except Exception as exc:  # the bus must never break a request or a job
        logger.debug("Live event not published (%s): %s", kind, exc)
        return None


async def replay(project_id: Any, after: int) -> list[dict[str, Any]]:
    """Events newer than ``after`` still in the short log, oldest first (empty when unavailable)."""
    from app.memory.short_term import get_valkey

    try:
        raw = await get_valkey().lrange(_log_key(project_id), 0, LOG_SIZE - 1)
        found = [orjson.loads(item) for item in raw]
    except Exception:
        return []
    return sorted((m for m in found if int(m["id"]) > after), key=lambda m: int(m["id"]))


async def _publish_all(items: list[tuple[str, str, dict[str, Any], int, list[str] | None]]) -> None:
    for project_id, kind, ids, classification, acl in items:
        await publish(project_id, kind, ids, classification=classification, acl=acl)


async def drain() -> None:
    """Wait for the publications scheduled by commits (shutdown, tests)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def _after_commit(session: Session) -> None:
    items = session.info.pop(_INFO_KEY, None)
    if not items:
        return
    try:
        task = asyncio.get_running_loop().create_task(_publish_all(items))
    except RuntimeError:  # no running loop (sync usage): nothing to notify
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _after_rollback(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)


def install() -> None:
    if not event.contains(Session, "after_commit", _after_commit):
        event.listen(Session, "after_commit", _after_commit)
        event.listen(Session, "after_rollback", _after_rollback)


install()
