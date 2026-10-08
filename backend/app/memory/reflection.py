"""Monthly reflection « ce qui a changé » (docs/AI_CONTEXT_ENGINEERING.md §D4).

Once a month (worker maintenance) or on demand (``POST /projects/{slug}/memory/reflect``), a ``reflect``
job summarises the memory events of a month — decisions validated, replacements, items made obsolete,
contradictions detected, restorations — into a **proposed** long-term ``summary`` item tagged
``reflection:<YYYY-MM>``. Every line cites the item and the change event it comes from (provenance rows
« Journal mémoire »); a human validates (or rejects) the proposal in the Revue mémoire.

Governance: only project-wide items (ACL ``project:*``, not user memory) are summarised; the summary
takes the highest classification of the cited items. The optional LLM introduction obeys the guardrail.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.enums import JobKind, JobStatus, MemoryEventType, MemoryKind, MemoryScope, MemoryStatus
from app.governance.acl import PROJECT_ALL
from app.llm import client as llm_client
from app.llm import guardrail
from app.models import IngestionJob, MemoryEvent, MemoryItem, Project
from app.schemas.memory import MemoryIn, ProvenanceIn
from app.services import audit
from app.services.audit import Actor, AuditAction

logger = logging.getLogger(__name__)

TAG = "reflection"
MAX_LINES_PER_SECTION = 25
MONTHS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
SECTIONS: tuple[tuple[MemoryEventType, str], ...] = (
    (MemoryEventType.validated, "Décisions et éléments validés"),
    (MemoryEventType.superseded, "Remplacements"),
    (MemoryEventType.obsoleted, "Devenus obsolètes"),
    (MemoryEventType.conflict_detected, "Contradictions détectées"),
    (MemoryEventType.restored, "Restaurations"),
)
LLM_SYSTEM = (
    "Tu rédiges en français, en trois phrases au plus, l'introduction d'une synthèse mensuelle « ce qui a "
    "changé » dans la mémoire d'un projet, à partir de la liste fournie. N'invente rien."
)


@dataclass(slots=True)
class Month:
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return f"{self.start.year:04d}-{self.start.month:02d}"

    @property
    def title(self) -> str:
        return f"{MONTHS_FR[self.start.month - 1]} {self.start.year}"


def month_of(label: str | None = None, now: datetime | None = None) -> Month:
    """``"2026-09"`` → that month; ``None`` → the month before ``now``."""
    if label:
        year, month = (int(part) for part in label.split("-", 1))
    else:
        current = now or utcnow()
        year, month = (current.year, current.month - 1) if current.month > 1 else (current.year - 1, 12)
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=UTC)
    return Month(start, end)


def _tag(month: Month) -> str:
    return f"{TAG}:{month.label}"


async def existing(session: AsyncSession, project_id: uuid.UUID, month: Month) -> MemoryItem | None:
    return await session.scalar(
        select(MemoryItem)
        .where(
            MemoryItem.project_id == project_id,
            MemoryItem.is_current.is_(True),
            MemoryItem.tags.any(_tag(month)),  # type: ignore[arg-type]
        )
        .limit(1)
    )


def _summarisable(item: MemoryItem) -> bool:
    return (
        MemoryScope(item.scope) in (MemoryScope.project, MemoryScope.long_term)
        and PROJECT_ALL in (item.acl_principals or [])
        and MemoryStatus(item.status) != MemoryStatus.forgotten
        and not _tag_prefix(item)
    )


def _tag_prefix(item: MemoryItem) -> bool:
    return any(str(tag).startswith(f"{TAG}:") for tag in item.tags or [])


async def reflect(
    session: AsyncSession, project_id: uuid.UUID, month: Month, actor: Any = None
) -> MemoryItem | None:
    """Create the proposed « ce qui a changé » summary of ``month`` (idempotent; ``None`` if nothing)."""
    from app.memory import lifecycle

    if await existing(session, project_id, month) is not None:
        return None
    rows = list(
        await session.execute(
            select(MemoryEvent, MemoryItem)
            .join(MemoryItem, MemoryItem.id == MemoryEvent.memory_item_id)
            .where(
                MemoryItem.project_id == project_id,
                MemoryEvent.created_at >= month.start,
                MemoryEvent.created_at < month.end,
                MemoryEvent.event.in_([event for event, _ in SECTIONS]),
            )
            .order_by(MemoryEvent.created_at, MemoryEvent.id)
        )
    )
    by_section: dict[MemoryEventType, list[tuple[MemoryEvent, MemoryItem]]] = {e: [] for e, _ in SECTIONS}
    seen: set[tuple[MemoryEventType, uuid.UUID]] = set()
    for event, item in rows:
        kind = MemoryEventType(event.event)
        if not _summarisable(item) or (kind, item.lineage_id) in seen:
            continue
        if kind == MemoryEventType.validated and MemoryKind(item.kind) == MemoryKind.summary:
            continue
        seen.add((kind, item.lineage_id))
        by_section[kind].append((event, item))
    cited = [pair for pairs in by_section.values() for pair in pairs[:MAX_LINES_PER_SECTION]]
    if not cited:
        return None

    lines: list[str] = []
    provenance: list[ProvenanceIn] = []
    for kind, heading in SECTIONS:
        pairs = by_section[kind][:MAX_LINES_PER_SECTION]
        if not pairs:
            continue
        lines += ["", f"### {heading}"]
        for event, item in pairs:
            date = event.created_at.strftime("%d/%m/%Y")
            reason = f" — {' '.join(event.reason.split())}" if event.reason else ""
            ref = len(provenance) + 1
            lines.append(f"- « {item.title} »{reason} ({date}) [J{ref}]")
            provenance.append(
                ProvenanceIn(
                    source_label=f"Journal mémoire · J{ref} · {heading} · {date}"[:300],
                    excerpt=f"Événement {event.id} sur l'item {item.id} (lignée {item.lineage_id})",
                )
            )
    level = max(int(item.classification) for _, item in cited)
    body = "\n".join(lines).strip()
    intro = await _llm_intro(body, level)
    header = f"Ce qui a changé dans la mémoire du projet en {month.title} ({len(cited)} changements)."
    content = "\n\n".join(part for part in (header, intro, body) if part)
    data = MemoryIn(
        scope=MemoryScope.long_term,
        kind=MemoryKind.summary,
        title=f"Ce qui a changé — {month.title}",
        content=content[:20000],
        classification=level,
        tags=[TAG, _tag(month)],
        valid_from=month.end,
        status="proposed",
        provenance=provenance[:50],
    )
    resolved = actor if actor is not None else Actor.system()
    item = await lifecycle.create_item(
        session,
        project_id=project_id,
        data=data,
        actor=resolved,
        force_status=MemoryStatus.proposed.value,
        detect=False,
    )
    await audit.record(
        session,
        project_id,
        resolved,
        AuditAction.memory_reflection,
        "memory",
        item.id,
        summary=f"Réflexion mensuelle proposée : {month.title} ({len(cited)} changements)",
        details={"month": month.label, "events": [str(event.id) for event, _ in cited]},
    )
    return item


async def _llm_intro(body: str, level: int) -> str:
    if not llm_client.is_enabled():
        return ""
    if not guardrail.allows(level):
        guardrail.record_skip(guardrail.REASON_CLASSIFICATION)
        return ""
    text = await llm_client.complete(LLM_SYSTEM, body[:6000], classification=level, max_tokens=250)
    return f"Synthèse : {' '.join(text.split())}" if text else ""


async def handle_reflect(session: AsyncSession, job: IngestionJob) -> None:
    """Job handler (``reflect``): payload ``{"month": "YYYY-MM"}``."""
    from app.ingestion.pipeline import actor_from_payload

    payload = job.payload or {}
    month = month_of(payload.get("month"))
    actor = actor_from_payload(payload.get("actor")) if payload.get("actor") else None
    item = await reflect(session, job.project_id, month, actor)
    job.payload = {**payload, "month": month.label, "memory_id": str(item.id) if item else None}


async def trigger_reflections(session: AsyncSession, now: datetime) -> int:
    """Worker maintenance: enqueue the previous month's reflection of every project once."""
    if not settings.memory_reflection:
        return 0
    from app.ingestion.queue import enqueue_job

    month = month_of(None, now)
    done = set(
        await session.scalars(
            select(IngestionJob.project_id).where(
                IngestionJob.kind == JobKind.reflect,
                IngestionJob.status != JobStatus.failed,
                IngestionJob.payload["month"].astext == month.label,
            )
        )
    )
    enqueued = 0
    for project_id in await session.scalars(select(Project.id)):
        if project_id in done:
            continue
        await enqueue_job(
            session, project_id, JobKind.reflect, payload={"month": month.label, "trigger": "maintenance"}
        )
        enqueued += 1
    return enqueued


__all__ = ["Month", "handle_reflect", "month_of", "reflect", "trigger_reflections"]
