"""``context.served`` change events (docs/FEATURES.md F2, live events).

One event per served context request, **never carrying content**: no task text, excerpt, title or
snapshot content, only ids, counts and the maximal classification served. High-frequency agents are
coalesced: requests of the same requester within ``ORBIT_CONTEXT_EVENTS_COALESCE_SECONDS`` update the
latest event (counter, last values, max classification) instead of adding a new row; the webhook
deliveries are queued once, with the first event of the window.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.features.feed import events
from app.features.feed.types import ChangeType
from app.governance.acl import PROJECT_ALL
from app.models.features_feed import ChangeEvent
from app.observability.metrics import CONTEXT_EVENTS_TOTAL

logger = logging.getLogger("orbit.feed.context")

HUMAN_GROUP = "explorer"
#: Keys of the event data that are never returned by the API (kept for webhooks as ids only).
PRIVATE_DATA_KEYS = ("on_behalf_of",)


@dataclass(slots=True)
class Served:
    project_id: uuid.UUID
    request_id: uuid.UUID
    trace_id: str
    agent_id: uuid.UUID | None
    agent_name: str | None
    on_behalf_of: uuid.UUID | None
    intent: str
    included_count: int
    excluded_count: int
    tokens_used: int
    token_budget: int
    latency_ms: int
    sufficiency: str | None = None
    snapshot: str | None = None
    max_classification: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _label(served: Served) -> str:
    return served.agent_name or "l'Explorateur"


def _title(served: Served) -> str:
    return f"Contexte servi à {_label(served)}"


def _summary(served: Served, count: int) -> str:
    detail = f"{served.included_count} retenus, {served.excluded_count} exclus, {served.tokens_used} tokens"
    if count <= 1:
        return f"Contexte servi à {_label(served)} : {detail}"
    return f"{count} contextes servis à {_label(served)} (dernier : {detail})"


def _data(served: Served, count: int) -> dict[str, Any]:
    data: dict[str, Any] = {
        "request_id": str(served.request_id),
        "trace_id": served.trace_id,
        "agent_id": str(served.agent_id) if served.agent_id else None,
        "agent_name": served.agent_name,
        "on_behalf_of": str(served.on_behalf_of) if served.on_behalf_of else None,
        "intent": served.intent,
        "included_count": served.included_count,
        "excluded_count": served.excluded_count,
        "tokens_used": served.tokens_used,
        "token_budget": served.token_budget,
        "latency_ms": served.latency_ms,
        "sufficiency": served.sufficiency,
        "snapshot": served.snapshot,
        "max_classification": served.max_classification,
        "count": count,
        "group": str(served.agent_id) if served.agent_id else HUMAN_GROUP,
    }
    return {k: v for k, v in data.items() if v is not None}


async def record(session: AsyncSession, served: Served) -> ChangeEvent | None:
    """Emit (or coalesce) the ``context.served`` event. Never raises: the context must be served."""
    if not settings.context_events:
        return None
    try:
        with session.no_autoflush:
            return await _record(session, served)
    except Exception:
        logger.exception("Unable to record the context.served event of %s", served.request_id)
        CONTEXT_EVENTS_TOTAL.labels(outcome="failed").inc()
        return None


async def _record(session: AsyncSession, served: Served) -> ChangeEvent:
    window = settings.context_events_coalesce_seconds
    now = utcnow()
    group = str(served.agent_id) if served.agent_id else HUMAN_GROUP
    if window > 0:
        previous = await session.scalar(
            select(ChangeEvent)
            .where(
                ChangeEvent.project_id == served.project_id,
                ChangeEvent.type == ChangeType.context_served.value,
                ChangeEvent.created_at >= now - timedelta(seconds=window),
                ChangeEvent.data["group"].astext == group,
            )
            .order_by(ChangeEvent.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if previous is not None:
            count = int((previous.data or {}).get("count", 1)) + 1
            served.max_classification = max(served.max_classification, int(previous.classification))
            previous.data = _data(served, count)
            previous.title = _title(served)
            previous.summary = _summary(served, count)[:1000]
            previous.classification = served.max_classification
            previous.created_at = now
            CONTEXT_EVENTS_TOTAL.labels(outcome="coalesced").inc()
            _publish(session, served, previous.id, count)
            return previous
    draft = events.Draft(
        type=ChangeType.context_served,
        title=_title(served),
        summary=_summary(served, 1),
        target_type="context_request",
        target_id=str(served.request_id),
        classification=served.max_classification,
        acl_principals=[PROJECT_ALL],
        data=_data(served, 1),
    )
    event = await events.emit(session, served.project_id, draft, _label(served))
    CONTEXT_EVENTS_TOTAL.labels(outcome="emitted").inc()
    _publish(session, served, event.id, 1)
    return event


def _publish(session: AsyncSession, served: Served, event_id: uuid.UUID, count: int) -> None:
    from app.features.live import bus

    bus.queue(
        session,
        served.project_id,
        "context.served",
        {
            "request_id": str(served.request_id),
            "event_id": str(event_id),
            "agent_id": str(served.agent_id) if served.agent_id else None,
            "count": count,
        },
        classification=served.max_classification,
    )
