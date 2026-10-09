"""Live event stream (Server-Sent Events) of a project: ids only, filtered by the viewer's rights.

``GET /api/v1/projects/{slug}/events/stream`` (cookie or Bearer, viewer role). Events: ``context.served``,
``ingestion.updated``, ``memory.changed``, ``snapshot.created`` (``data`` = ids and counters, never
content), ``degraded`` (the bus is unavailable: poll instead) and ``reconnect`` (planned end of the
stream). Heartbeat comment every ``ORBIT_LIVE_STREAM_HEARTBEAT_SECONDS``; ``Last-Event-ID`` (header or
``last_event_id`` query) replays what is still in the short per-project log.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

import orjson
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.db import get_sessionmaker
from app.deps import get_principal, get_project_access
from app.enums import Role
from app.errors import ApiError, not_found
from app.features.feed.service import FeedViewer
from app.features.live import bus
from app.observability.metrics import LIVE_CONNECTIONS, LIVE_EVENTS_DELIVERED_TOTAL

logger = logging.getLogger("orbit.live")

router = APIRouter(prefix="/projects/{slug}", tags=["live"])

#: A stream is closed (the client reconnects) after this long: re-checks rights, frees dead peers.
MAX_STREAM_SECONDS = 300
HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

_per_user: Counter[str] = Counter()
_total = 0


def _visible(message: dict[str, Any], viewer: FeedViewer) -> bool:
    if int(message.get("classification") or 0) > viewer.clearance:
        return False
    acl = message.get("acl")
    return not acl or bool(set(acl) & viewer.principals)


def _frame(message: dict[str, Any]) -> bytes:
    body = orjson.dumps({"kind": message["kind"], "id": message["id"], **(message.get("data") or {})})
    LIVE_EVENTS_DELIVERED_TOTAL.labels(kind=message["kind"]).inc()
    return f"id: {message['id']}\nevent: {message['kind']}\ndata: {body.decode()}\n\n".encode()


def _parse_id(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


async def _events(
    request: Request, project_id: Any, viewer: FeedViewer, last_id: int | None
) -> AsyncIterator[bytes]:
    from app.memory.short_term import get_valkey

    yield b"retry: 3000\n: connected\n\n"
    pubsub = None
    try:
        pubsub = get_valkey().pubsub()
        await pubsub.subscribe(bus.channel(project_id))
        replayed = last_id or 0
        if last_id is not None:
            for message in await bus.replay(project_id, last_id):
                replayed = max(replayed, int(message["id"]))
                if _visible(message, viewer):
                    yield _frame(message)
        started = last_beat = time.monotonic()
        while True:
            now = time.monotonic()
            if now - started > MAX_STREAM_SECONDS:
                yield b"event: reconnect\ndata: {}\n\n"
                return
            if now - last_beat >= settings.live_stream_heartbeat_seconds:
                yield b": ping\n\n"
                last_beat = now
                if await request.is_disconnected():
                    return
            raw = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=min(1.0, settings.live_stream_heartbeat_seconds)
            )
            if raw is None:
                continue
            message = orjson.loads(raw["data"])
            if int(message["id"]) <= replayed or not _visible(message, viewer):
                continue
            yield _frame(message)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # Valkey down: the client falls back to polling
        logger.info("Live stream degraded (%s)", type(exc).__name__)
        yield b"event: degraded\ndata: {}\n\n"
    finally:
        if pubsub is not None:
            with contextlib.suppress(Exception):
                await pubsub.aclose()


@router.get("/events/stream", summary="Flux d'événements en direct (SSE, identifiants uniquement)")
async def stream(slug: str, request: Request, last_event_id: str | None = None) -> StreamingResponse:
    global _total
    if not settings.live_stream:
        raise not_found("Flux en direct désactivé")
    # Authenticate with a short-lived session: no database connection is held while streaming.
    async with get_sessionmaker()() as session:
        principal = await get_principal(request, session)
        access = await get_project_access(session, principal, slug, Role.viewer)
        viewer = FeedViewer.from_access(access)
    key = f"{principal.kind}:{principal.id}"
    if _total >= settings.live_stream_max_connections_total or (
        _per_user[key] >= settings.live_stream_max_connections_per_user
    ):
        raise ApiError(
            429, "Trop de flux en direct ouverts", code="too_many_streams", headers={"Retry-After": "10"}
        )
    last_id = _parse_id(request.headers.get("last-event-id") or last_event_id)

    async def body() -> AsyncIterator[bytes]:
        global _total
        _total += 1
        _per_user[key] += 1
        LIVE_CONNECTIONS.inc()
        try:
            async for chunk in _events(request, access.project_id, viewer, last_id):
                yield chunk
        finally:
            _total -= 1
            _per_user[key] -= 1
            if _per_user[key] <= 0:
                del _per_user[key]
            LIVE_CONNECTIONS.dec()

    return StreamingResponse(body(), media_type="text/event-stream", headers=HEADERS)
