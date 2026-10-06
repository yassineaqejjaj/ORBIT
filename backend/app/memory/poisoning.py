"""Memory poisoning alert (docs/AI_CONTEXT_ENGINEERING.md §A3).

A *burst* of memory proposals / facts coming from a single recent source, or from a single agent,
is the signature of a poisoning attempt (someone feeding the project memory through one channel).
Within ``ORBIT_POISONING_WINDOW_HOURS``, a source created inside the window or an agent that produced at
least ``ORBIT_POISONING_ALERT_THRESHOLD`` memory items raises an alert: shown in the overview attention
list and recorded once per window in the audit log (``security.poisoning_alert``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.enums import ActorType, MemoryStatus
from app.models import Agent, AuditLog, Document, MemoryItem, MemoryProvenance, Source
from app.services import audit
from app.services.audit import Actor, AuditAction

_WATCHED_STATUSES = (MemoryStatus.proposed, MemoryStatus.validated)


@dataclass(frozen=True, slots=True)
class PoisoningSignal:
    kind: str  # "source" | "agent"
    target_id: uuid.UUID
    label: str
    count: int

    @property
    def message(self) -> str:
        origin = (
            f"la source récente « {self.label} »" if self.kind == "source" else f"l'agent « {self.label} »"
        )
        return (
            f"Empoisonnement possible de la mémoire : {self.count} propositions/faits en "
            f"{settings.poisoning_window_hours} h venant de {origin} — vérifiez avant toute validation."
        )


async def detect(
    session: AsyncSession, project_id: uuid.UUID, now: datetime | None = None
) -> list[PoisoningSignal]:
    """Sources (created within the window) and agents above the threshold, biggest bursts first."""
    now = now or utcnow()
    since = now - timedelta(hours=settings.poisoning_window_hours)
    threshold = settings.poisoning_alert_threshold
    recent_items = (
        MemoryItem.project_id == project_id,
        MemoryItem.created_at >= since,
        MemoryItem.status.in_(_WATCHED_STATUSES),
    )
    by_source = await session.execute(
        select(Source.id, Source.name, func.count(func.distinct(MemoryItem.id)))
        .select_from(MemoryItem)
        .join(MemoryProvenance, MemoryProvenance.memory_item_id == MemoryItem.id)
        .join(Document, Document.id == MemoryProvenance.document_id)
        .join(Source, Source.id == Document.source_id)
        .where(*recent_items, Source.created_at >= since)
        .group_by(Source.id, Source.name)
        .having(func.count(func.distinct(MemoryItem.id)) >= threshold)
    )
    by_agent = await session.execute(
        select(Agent.id, Agent.name, func.count(MemoryItem.id))
        .select_from(MemoryItem)
        .join(Agent, Agent.id == MemoryItem.created_by_id)
        .where(*recent_items, MemoryItem.created_by_type == ActorType.agent)
        .group_by(Agent.id, Agent.name)
        .having(func.count(MemoryItem.id) >= threshold)
    )
    signals = [PoisoningSignal("source", sid, name, int(n)) for sid, name, n in by_source.tuples()]
    signals += [PoisoningSignal("agent", aid, name, int(n)) for aid, name, n in by_agent.tuples()]
    return sorted(signals, key=lambda s: -s.count)


async def check_and_record(session: AsyncSession, project_id: uuid.UUID) -> list[PoisoningSignal]:
    """Detect bursts and audit each one at most once per window (flushes, never commits)."""
    signals = await detect(session, project_id)
    if not signals:
        return []
    since = utcnow() - timedelta(hours=settings.poisoning_window_hours)
    already: set[str | None] = set(
        await session.scalars(
            select(AuditLog.target_id).where(
                AuditLog.project_id == project_id,
                AuditLog.action == AuditAction.poisoning_alert.value,
                AuditLog.created_at >= since,
            )
        )
    )
    for signal in signals:
        if str(signal.target_id) in already:
            continue
        await audit.record(
            session,
            project_id,
            Actor.system(),
            AuditAction.poisoning_alert,
            signal.kind,
            signal.target_id,
            signal.message,
            {"count": signal.count, "window_hours": settings.poisoning_window_hours, "kind": signal.kind},
        )
    return signals
