"""Project overview, observability aggregates and trace export (ARCHITECTURE §11, docs/API.md).

Everything is aggregated from Postgres (the source of truth), so the numbers survive restarts and do
not depend on the Prometheus registry of a given process.

Non-leak principle (§3): counters are global to the project, but **titles** (top sources, latest
decisions) and **excerpts** (trace export) are only returned for content the caller may read
(content ACL + classification ≤ clearance). Restricted audit details are stripped for non-owners.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import orjson
from sqlalchemy import Date, and_, cast, exists, func, literal, literal_column, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db import get_sessionmaker, utcnow
from app.deps import ProjectAccess
from app.enums import (
    RESTRICTED_CLASSIFICATION_MIN,
    ActorType,
    AlertLevel,
    CandidateType,
    ChunkStatus,
    ContextRequestStatus,
    DocumentStatus,
    JobKind,
    JobStatus,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    ReasonCode,
    RelationType,
    SourceKind,
)
from app.governance.acl import acl_allows, effective_principals
from app.models import (
    Agent,
    AuditLog,
    Chunk,
    ContextDecision,
    ContextFeedback,
    ContextRequest,
    ContextSnapshot,
    Document,
    IngestionJob,
    MemoryItem,
    MemoryProvenance,
    Relation,
    Source,
    User,
)
from app.schemas import (
    AgentUsage,
    Alert,
    AuditEvent,
    IngestionMetrics,
    Metrics,
    MetricsPoint,
    MetricsTotals,
    Overview,
    OverviewContext,
    OverviewIngestion,
    OverviewStats,
    TopSource,
)
from app.schemas import MemoryItem as MemoryItemOut
from app.services import audit as audit_service
from app.services import projects as project_service

logger = logging.getLogger("orbit.metrics")

#: Window of the overview's context aggregates.
OVERVIEW_WINDOW_DAYS = 7
LATEST_DECISIONS_LIMIT = 5
RECENT_ACTIVITY_LIMIT = 15
TOP_SOURCES_LIMIT = 10
#: Candidates fetched before visibility filtering (hidden documents are dropped, not replaced by ids).
TOP_SOURCES_SCAN = 60
#: Proposals above which the review backlog becomes a warning.
PROPOSALS_WARNING_THRESHOLD = 10
TRACE_EXPORT_BATCH = 200
TRACE_SCHEMA = "orbit.trace.v1"

#: Display order of the assembly stages (§9); unknown keys follow alphabetically, ``total`` last.
STAGE_ORDER: tuple[str, ...] = (
    "understand",
    "retrieve",
    "fuse",
    "rerank",
    "govern",
    "select",
    "compress",
    "package",
    "persist",
)
#: Memory statuses of a contradiction endpoint that keep the conflict open.
OPEN_MEMORY_STATUSES: tuple[MemoryStatus, ...] = (MemoryStatus.proposed, MemoryStatus.validated)
REDACTED_CONTEXT = "[caviardé — ce contexte contient des contenus au-delà de votre habilitation]"

_UTC = literal_column("'UTC'")


# --- Visibility -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Visibility:
    """What the caller may read: content ACL principals and clearance (§3)."""

    principals: frozenset[str]
    clearance: int

    @classmethod
    def for_access(cls, access: ProjectAccess) -> Visibility:
        return cls(frozenset(effective_principals(access)), int(access.principal.clearance))

    def allows(self, acl_principals: Sequence[str] | None, classification: int | None) -> bool:
        return int(classification or 0) <= self.clearance and acl_allows(acl_principals, self.principals)


# --- Pure helpers (unit-tested) -----------------------------------------------------------------------


def window_start(days: int, *, now: datetime | None = None) -> datetime:
    """UTC midnight of the first day of a ``days``-day window that ends today (inclusive)."""
    today = (now or utcnow()).astimezone(UTC).date()
    return datetime.combine(today - timedelta(days=max(days, 1) - 1), time.min, tzinfo=UTC)


def window_days(days: int, *, now: datetime | None = None) -> list[date]:
    first = window_start(days, now=now).date()
    return [first + timedelta(days=offset) for offset in range(max(days, 1))]


def rounded(value: Any, digits: int = 1) -> float:
    """``None``/``Decimal``/``float`` → rounded ``float`` (``0.0`` for missing values)."""
    if value is None:
        return 0.0
    return round(float(value), digits)


def zero_fill_series(points: Mapping[date, MetricsPoint], days: Iterable[date]) -> list[MetricsPoint]:
    """One point per day, in order; days without requests are explicit zeros."""
    return [points.get(day) or MetricsPoint(date=day) for day in days]


def order_stages(averages: Mapping[str, float]) -> dict[str, float]:
    known = [key for key in STAGE_ORDER if key in averages]
    others = sorted(key for key in averages if key not in STAGE_ORDER and key != "total")
    ordered = {key: averages[key] for key in (*known, *others)}
    if "total" in averages:
        ordered["total"] = averages["total"]
    return ordered


def inclusion_key(candidate_type: CandidateType | str, memory_kind: MemoryKind | str | None) -> str:
    """``chunk`` / ``session`` / ``memory:<kind>`` (``memory`` when the item no longer exists)."""
    kind = str(getattr(candidate_type, "value", candidate_type))
    if kind == CandidateType.memory.value:
        return f"memory:{getattr(memory_kind, 'value', memory_kind)}" if memory_kind else "memory"
    return kind


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count <= 1 else plural}"


@dataclass(frozen=True, slots=True)
class AlertSignals:
    """Raw counters from which the overview alerts are derived."""

    sources: int = 0
    failed_jobs: int = 0
    queued_jobs: int = 0
    running_jobs: int = 0
    open_conflicts: int = 0
    pending_proposals: int = 0
    c2_documents: int = 0
    c3_documents: int = 0


_ALERT_RANK = {AlertLevel.critical: 0, AlertLevel.warning: 1, AlertLevel.info: 2}


def build_alerts(signals: AlertSignals) -> list[Alert]:
    """French alerts, most severe first."""
    alerts: list[Alert] = []
    if signals.failed_jobs:
        alerts.append(
            Alert(
                level=AlertLevel.critical,
                message=_plural(signals.failed_jobs, "job d'ingestion en échec", "jobs d'ingestion en échec")
                + " — relancez le traitement depuis l'écran Sources.",
            )
        )
    if signals.open_conflicts:
        alerts.append(
            Alert(
                level=AlertLevel.warning,
                message=_plural(
                    signals.open_conflicts, "contradiction non résolue", "contradictions non résolues"
                )
                + " dans la mémoire du projet — arbitrage recommandé.",
            )
        )
    if signals.c3_documents:
        alerts.append(
            Alert(
                level=AlertLevel.warning,
                message=_plural(
                    signals.c3_documents, "document classifié C3 (Secret)", "documents classifiés C3 (Secret)"
                )
                + " dans le projet — accès limité aux habilitations C3.",
            )
        )
    if signals.pending_proposals:
        level = (
            AlertLevel.warning
            if signals.pending_proposals >= PROPOSALS_WARNING_THRESHOLD
            else AlertLevel.info
        )
        alerts.append(
            Alert(
                level=level,
                message=_plural(
                    signals.pending_proposals,
                    "proposition de mémoire en attente de validation",
                    "propositions de mémoire en attente de validation",
                )
                + ".",
            )
        )
    if signals.c2_documents:
        alerts.append(
            Alert(
                level=AlertLevel.info,
                message=_plural(
                    signals.c2_documents,
                    "document classifié C2 (Confidentiel)",
                    "documents classifiés C2 (Confidentiel)",
                )
                + " — un avertissement est affiché dès qu'ils sont servis.",
            )
        )
    if signals.queued_jobs or signals.running_jobs:
        alerts.append(
            Alert(
                level=AlertLevel.info,
                message=f"Ingestion en cours : {_plural(signals.queued_jobs, 'job', 'jobs')} en file "
                f"d'attente, {signals.running_jobs} en traitement.",
            )
        )
    if signals.sources == 0:
        alerts.append(
            Alert(
                level=AlertLevel.info,
                message="Aucune source configurée — ajoutez une source pour alimenter le contexte du projet.",
            )
        )
    return sorted(alerts, key=lambda alert: _ALERT_RANK[alert.level])


# --- Shared queries ---------------------------------------------------------------------------------


async def _count(session: AsyncSession, column: Any, *conditions: Any) -> int:
    return int(await session.scalar(select(func.count(column)).where(*conditions)) or 0)


async def _count_by(session: AsyncSession, key: Any, *conditions: Any) -> dict[Any, int]:
    rows = await session.execute(select(key, func.count()).where(*conditions).group_by(key))
    return {value: int(count) for value, count in rows.tuples()}


async def actor_labels(
    session: AsyncSession, actors: Iterable[tuple[ActorType | str | None, uuid.UUID | None]]
) -> dict[uuid.UUID, str]:
    """Display labels of user/agent actors (full name / agent name)."""
    user_ids: set[uuid.UUID] = set()
    agent_ids: set[uuid.UUID] = set()
    for actor_type, actor_id in actors:
        if actor_id is None:
            continue
        if str(actor_type) == ActorType.agent.value:
            agent_ids.add(actor_id)
        elif str(actor_type) == ActorType.user.value:
            user_ids.add(actor_id)
    labels: dict[uuid.UUID, str] = {}
    if user_ids:
        rows = await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(user_ids)))
        labels.update({uid: name or email for uid, name, email in rows.tuples()})
    if agent_ids:
        rows = await session.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        labels.update(dict(rows.tuples().all()))
    return labels


async def memory_views(session: AsyncSession, items: Sequence[MemoryItem]) -> list[MemoryItemOut]:
    """Serialise memory items with ``created_by_label`` and ``provenance_count`` (all versions)."""
    if not items:
        return []
    lineages = {item.lineage_id for item in items}
    rows = await session.execute(
        select(MemoryItem.lineage_id, func.count(MemoryProvenance.id))
        .join(MemoryProvenance, MemoryProvenance.memory_item_id == MemoryItem.id)
        .where(MemoryItem.lineage_id.in_(lineages))
        .group_by(MemoryItem.lineage_id)
    )
    provenance = {lineage: int(count) for lineage, count in rows.tuples()}
    labels = await actor_labels(session, [(i.created_by_type, i.created_by_id) for i in items])
    views: list[MemoryItemOut] = []
    for item in items:
        if item.created_by_id is not None:
            label = labels.get(item.created_by_id, "")
        else:
            label = audit_service.SYSTEM_LABEL if item.created_by_type == ActorType.system else ""
        views.append(
            MemoryItemOut.model_validate(item).model_copy(
                update={"created_by_label": label, "provenance_count": provenance.get(item.lineage_id, 0)}
            )
        )
    return views


async def count_open_conflicts(session: AsyncSession, project_id: uuid.UUID) -> int:
    """``contradicts`` relations whose endpoints are all still active.

    A contradiction is resolved once one side is superseded / obsolete / forgotten (memory items are
    followed to the current version of their lineage), a chunk is no longer active or a document has
    been forgotten.
    """
    ref = aliased(MemoryItem)
    current = aliased(MemoryItem)
    endpoints = [Relation.src_id, Relation.dst_id]
    memory_closed = exists(
        select(literal(1))
        .select_from(ref)
        .join(current, and_(current.lineage_id == ref.lineage_id, current.is_current.is_(True)))
        .where(ref.id.in_(endpoints), current.status.not_in(OPEN_MEMORY_STATUSES))
    )
    chunk_closed = exists(
        select(literal(1)).where(Chunk.id.in_(endpoints), Chunk.status != ChunkStatus.active)
    )
    document_closed = exists(
        select(literal(1)).where(Document.id.in_(endpoints), Document.status == DocumentStatus.forgotten)
    )
    stmt = select(func.count(Relation.id)).where(
        Relation.project_id == project_id,
        Relation.rel_type == RelationType.contradicts,
        ~memory_closed,
        ~chunk_closed,
        ~document_closed,
    )
    return int(await session.scalar(stmt) or 0)


async def count_failed_jobs(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Failed jobs not followed by a newer job of the same kind on the same document (still broken)."""
    later = aliased(IngestionJob)
    retried = exists(
        select(literal(1)).where(
            later.document_id == IngestionJob.document_id,
            later.kind == IngestionJob.kind,
            later.created_at > IngestionJob.created_at,
            later.status != JobStatus.failed,
        )
    )
    return await _count(
        session,
        IngestionJob.id,
        IngestionJob.project_id == project_id,
        IngestionJob.status == JobStatus.failed,
        ~retried,
    )


# --- Overview ---------------------------------------------------------------------------------------


async def build_overview(session: AsyncSession, access: ProjectAccess) -> Overview:
    """``GET /projects/{slug}/overview``."""
    project = access.project
    pid = project.id
    visibility = Visibility.for_access(access)
    now = utcnow()
    since_7d = now - timedelta(days=OVERVIEW_WINDOW_DAYS)

    live_document = and_(Document.project_id == pid, Document.status != DocumentStatus.forgotten)
    current_memory = and_(MemoryItem.project_id == pid, MemoryItem.is_current.is_(True))

    sources_by_kind = await _count_by(session, Source.kind, Source.project_id == pid)
    documents_by_status = await _count_by(session, Document.status, Document.project_id == pid)
    by_classification = await _count_by(session, Document.classification, live_document)
    memory_by_status = await _count_by(session, MemoryItem.status, current_memory)
    memory_by_scope = await _count_by(
        session, MemoryItem.scope, current_memory, MemoryItem.status != MemoryStatus.forgotten
    )
    jobs_by_status = await _count_by(session, IngestionJob.status, IngestionJob.project_id == pid)

    stats = OverviewStats(
        sources=sum(sources_by_kind.values()),
        documents=sum(c for s, c in documents_by_status.items() if s != DocumentStatus.forgotten),
        documents_indexed=documents_by_status.get(DocumentStatus.indexed, 0),
        chunks=await _count(session, Chunk.id, Chunk.project_id == pid, Chunk.status == ChunkStatus.active),
        memory_items=sum(c for s, c in memory_by_status.items() if s != MemoryStatus.forgotten),
        validated_decisions=await _count(
            session,
            MemoryItem.id,
            current_memory,
            MemoryItem.kind == MemoryKind.decision,
            MemoryItem.status == MemoryStatus.validated,
        ),
        context_requests_7d=await _count(
            session,
            ContextRequest.id,
            ContextRequest.project_id == pid,
            ContextRequest.created_at >= since_7d,
        ),
        snapshots=await _count(session, ContextSnapshot.id, ContextSnapshot.project_id == pid),
        pii_documents=await _count(session, Document.id, live_document, Document.pii_count > 0),
        restricted_documents=sum(
            c for level, c in by_classification.items() if int(level) >= RESTRICTED_CLASSIFICATION_MIN
        ),
    )

    failed_jobs = await count_failed_jobs(session, pid)
    ingestion = OverviewIngestion(
        queued=jobs_by_status.get(JobStatus.queued, 0),
        running=jobs_by_status.get(JobStatus.running, 0),
        failed=failed_jobs,
        succeeded_24h=await _count(
            session,
            IngestionJob.id,
            IngestionJob.project_id == pid,
            IngestionJob.status == JobStatus.succeeded,
            IngestionJob.finished_at >= now - timedelta(hours=24),
        ),
    )

    context = await _context_aggregates(session, pid, since_7d, stats.context_requests_7d)
    latest_decisions = await _latest_decisions(session, pid, visibility)
    recent_activity = await _recent_activity(session, access)

    pending_proposals = await _count(
        session,
        MemoryItem.id,
        current_memory,
        MemoryItem.status == MemoryStatus.proposed,
        MemoryItem.scope != MemoryScope.short_term,
    )
    alerts = build_alerts(
        AlertSignals(
            sources=stats.sources,
            failed_jobs=failed_jobs,
            queued_jobs=ingestion.queued,
            running_jobs=ingestion.running,
            open_conflicts=await count_open_conflicts(session, pid),
            pending_proposals=pending_proposals,
            c2_documents=by_classification.get(2, 0),
            c3_documents=by_classification.get(3, 0),
        )
    )

    return Overview(
        project=project_service.to_schema(project, access.role),
        stats=stats,
        ingestion=ingestion,
        memory_by_status={status: memory_by_status.get(status, 0) for status in MemoryStatus},
        memory_by_scope={scope: memory_by_scope.get(scope, 0) for scope in MemoryScope},
        context=context,
        sources_by_kind={kind: sources_by_kind.get(kind, 0) for kind in SourceKind},
        latest_decisions=latest_decisions,
        recent_activity=recent_activity,
        alerts=alerts,
    )


async def _context_aggregates(
    session: AsyncSession, project_id: uuid.UUID, since: datetime, requests: int
) -> OverviewContext:
    succeeded = ContextRequest.status == ContextRequestStatus.succeeded
    row = (
        await session.execute(
            select(
                func.percentile_cont(0.95).within_group(ContextRequest.latency_ms),
                func.avg(ContextRequest.tokens_used),
                func.avg(ContextRequest.included_count),
                func.coalesce(func.sum(ContextRequest.excluded_count), 0),
                func.coalesce(func.sum(ContextRequest.included_count + ContextRequest.excluded_count), 0),
            ).where(ContextRequest.project_id == project_id, ContextRequest.created_at >= since, succeeded)
        )
    ).one()
    p95, avg_tokens, avg_included, excluded, decided = row
    return OverviewContext(
        requests_7d=requests,
        p95_latency_ms=rounded(p95),
        avg_tokens=rounded(avg_tokens),
        avg_included=rounded(avg_included),
        exclusion_rate=round(int(excluded) / int(decided), 3) if decided else 0.0,
    )


async def _latest_decisions(
    session: AsyncSession, project_id: uuid.UUID, visibility: Visibility
) -> list[MemoryItemOut]:
    rows = await session.scalars(
        select(MemoryItem)
        .where(
            MemoryItem.project_id == project_id,
            MemoryItem.is_current.is_(True),
            MemoryItem.kind == MemoryKind.decision,
            MemoryItem.status == MemoryStatus.validated,
        )
        .order_by(MemoryItem.updated_at.desc(), MemoryItem.id)
        .limit(LATEST_DECISIONS_LIMIT * 5)
    )
    visible = [item for item in rows if visibility.allows(item.acl_principals, item.classification)]
    return await memory_views(session, visible[:LATEST_DECISIONS_LIMIT])


async def _recent_activity(session: AsyncSession, access: ProjectAccess) -> list[AuditEvent]:
    rows, _total = await audit_service.list_events(session, access.project_id, limit=RECENT_ACTIVITY_LIMIT)
    return await audit_event_views(session, access, rows)


def audit_event_view(row: AuditLog, *, can_see_restricted: bool) -> AuditEvent:
    return AuditEvent.model_validate(row).model_copy(
        update={"details": audit_service.visible_details(row.details, can_see_restricted=can_see_restricted)}
    )


REDACTED_AUDIT_SUMMARY = "Action sur un contenu hors de vos droits d'accès (détail caviardé)"
#: Audit target types whose summary may quote a content title (documents, memory items, chunks).
CONTENT_TARGET_TYPES: frozenset[str] = frozenset({"document", "memory", "chunk"})


def _target_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def hidden_audit_targets(
    session: AsyncSession, visibility: Visibility, rows: Sequence[AuditLog]
) -> set[str]:
    """Target ids (as stored) of audit rows about content the caller cannot read (ACL / clearance)."""
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for row in rows:
        target = _target_uuid(row.target_id)
        if target is not None and row.target_type in CONTENT_TARGET_TYPES:
            wanted[row.target_type].add(target)
    if not wanted:
        return set()
    readable: dict[uuid.UUID, bool] = {}
    models: dict[str, Any] = {"document": Document, "memory": MemoryItem, "chunk": Chunk}
    for target_type, ids in wanted.items():
        model = models[target_type]
        result = await session.execute(
            select(model.id, model.acl_principals, model.classification).where(model.id.in_(ids))
        )
        for target_id, acl, level in result.tuples():
            readable[target_id] = visibility.allows(acl, level)
    # Unknown targets (deleted rows) are hidden too: nothing proves the caller could read them.
    return {str(target) for ids in wanted.values() for target in ids if not readable.get(target, False)}


async def audit_event_views(
    session: AsyncSession, access: ProjectAccess, rows: Sequence[AuditLog]
) -> list[AuditEvent]:
    """Audit rows as seen by the caller (non-leak principle, §3).

    Owners and admins see everything. Other members get ``details["restricted"]`` stripped and,
    for events about a document / memory item / chunk they cannot read, a generic summary without
    target id nor details (audit summaries quote content titles).
    """
    can_see = access.can_see_restricted_details
    hidden = set() if can_see else await hidden_audit_targets(session, Visibility.for_access(access), rows)
    views: list[AuditEvent] = []
    for row in rows:
        view = audit_event_view(row, can_see_restricted=can_see)
        if row.target_id is not None and row.target_id in hidden:
            redacted = {"summary": REDACTED_AUDIT_SUMMARY, "target_id": None, "details": {}}
            view = view.model_copy(update=redacted)
        views.append(view)
    return views


# --- Metrics ----------------------------------------------------------------------------------------


async def build_metrics(session: AsyncSession, access: ProjectAccess, *, days: int = 14) -> Metrics:
    """``GET /projects/{slug}/metrics?days=`` — one point per UTC day, zero-filled."""
    pid = access.project_id
    since = window_start(days)
    in_window = and_(ContextRequest.project_id == pid, ContextRequest.created_at >= since)
    succeeded = ContextRequest.status == ContextRequestStatus.succeeded

    series = await _series(session, in_window, succeeded, days)
    totals = await _totals(session, in_window, succeeded)

    exclusion_rows = await session.execute(
        select(ContextDecision.reason_code, func.count())
        .join(ContextRequest, ContextRequest.id == ContextDecision.request_id)
        .where(in_window, ContextDecision.included.is_(False))
        .group_by(ContextDecision.reason_code)
    )
    exclusions = {ReasonCode(code): int(count) for code, count in exclusion_rows.tuples()}
    exclusions_by_reason = {code: exclusions[code] for code in ReasonCode if exclusions.get(code)}

    inclusion_rows = await session.execute(
        select(ContextDecision.candidate_type, MemoryItem.kind, func.count())
        .join(ContextRequest, ContextRequest.id == ContextDecision.request_id)
        .outerjoin(MemoryItem, MemoryItem.id == ContextDecision.memory_item_id)
        .where(in_window, ContextDecision.included.is_(True))
        .group_by(ContextDecision.candidate_type, MemoryItem.kind)
    )
    inclusions: dict[str, int] = defaultdict(int)
    for candidate_type, memory_kind, count in inclusion_rows.tuples():
        inclusions[inclusion_key(candidate_type, memory_kind)] += int(count)
    inclusions_by_type = dict(sorted(inclusions.items(), key=lambda kv: (-kv[1], kv[0])))

    return Metrics(
        totals=totals,
        series=series,
        exclusions_by_reason=exclusions_by_reason,
        inclusions_by_type=inclusions_by_type,
        top_sources=await _top_sources(session, in_window, Visibility.for_access(access)),
        by_agent=await _by_agent(session, in_window),
        stage_latency_avg=await _stage_latency(session, pid, since),
        ingestion=await _ingestion_metrics(session, pid, since),
    )


async def _series(session: AsyncSession, in_window: Any, succeeded: Any, days: int) -> list[MetricsPoint]:
    day = cast(func.timezone(_UTC, ContextRequest.created_at), Date).label("day")
    rows = await session.execute(
        select(
            day,
            func.count(ContextRequest.id),
            func.percentile_cont(0.5).within_group(ContextRequest.latency_ms).filter(succeeded),
            func.percentile_cont(0.95).within_group(ContextRequest.latency_ms).filter(succeeded),
            func.coalesce(func.sum(ContextRequest.tokens_used), 0),
            func.coalesce(func.sum(ContextRequest.cost_estimate), 0),
        )
        .where(in_window)
        .group_by(day)
    )
    points = {
        row_day: MetricsPoint(
            date=row_day,
            requests=int(count),
            p50_latency_ms=rounded(p50),
            p95_latency_ms=rounded(p95),
            tokens=int(tokens),
            cost_estimate=rounded(cost, 6),
        )
        for row_day, count, p50, p95, tokens, cost in rows.tuples()
    }
    return zero_fill_series(points, window_days(days))


async def _totals(session: AsyncSession, in_window: Any, succeeded: Any) -> MetricsTotals:
    row = (
        await session.execute(
            select(
                func.count(ContextRequest.id),
                func.avg(ContextRequest.latency_ms).filter(succeeded),
                func.percentile_cont(0.5).within_group(ContextRequest.latency_ms).filter(succeeded),
                func.percentile_cont(0.95).within_group(ContextRequest.latency_ms).filter(succeeded),
                func.coalesce(func.sum(ContextRequest.tokens_used), 0),
                func.coalesce(func.sum(ContextRequest.cost_estimate), 0),
            ).where(in_window)
        )
    ).one()
    requests, avg_latency, p50, p95, tokens, cost = row
    feedback = (
        await session.execute(
            select(func.avg(ContextFeedback.rating), func.count(ContextFeedback.id))
            .join(ContextRequest, ContextRequest.id == ContextFeedback.request_id)
            .where(in_window)
        )
    ).one()
    avg_rating, feedback_count = feedback
    return MetricsTotals(
        requests=int(requests),
        avg_latency_ms=rounded(avg_latency),
        p50_latency_ms=rounded(p50),
        p95_latency_ms=rounded(p95),
        tokens=int(tokens),
        cost_estimate=rounded(cost, 6),
        avg_rating=rounded(avg_rating, 2) if avg_rating is not None else None,
        feedback_count=int(feedback_count),
    )


async def _top_sources(session: AsyncSession, in_window: Any, visibility: Visibility) -> list[TopSource]:
    usage = func.count(ContextDecision.id).label("usage")
    ranked = (
        await session.execute(
            select(ContextDecision.document_id, usage)
            .join(ContextRequest, ContextRequest.id == ContextDecision.request_id)
            .where(in_window, ContextDecision.included.is_(True), ContextDecision.document_id.is_not(None))
            .group_by(ContextDecision.document_id)
            .order_by(usage.desc(), ContextDecision.document_id)
            .limit(TOP_SOURCES_SCAN)
        )
    ).all()
    if not ranked:
        return []
    documents = {
        doc.id: (doc, kind)
        for doc, kind in (
            await session.execute(
                select(Document, Source.kind)
                .join(Source, Source.id == Document.source_id)
                .where(Document.id.in_([doc_id for doc_id, _ in ranked]))
            )
        ).tuples()
    }
    top: list[TopSource] = []
    for document_id, count in ranked:
        entry = documents.get(document_id)
        if entry is None:
            continue
        document, kind = entry
        # Hidden documents are dropped entirely: neither title nor id reaches the caller (§3).
        if document.status == DocumentStatus.forgotten or not visibility.allows(
            document.acl_principals, document.classification
        ):
            continue
        top.append(
            TopSource(document_id=document.id, title=document.title, source_kind=kind, count=int(count))
        )
        if len(top) >= TOP_SOURCES_LIMIT:
            break
    return top


async def _by_agent(session: AsyncSession, in_window: Any) -> list[AgentUsage]:
    requests = func.count(ContextRequest.id).label("requests")
    rows = await session.execute(
        select(
            Agent.id,
            Agent.name,
            Agent.kind,
            requests,
            func.avg(ContextRequest.latency_ms),
            func.avg(ContextRequest.tokens_used),
        )
        .join(ContextRequest, ContextRequest.agent_id == Agent.id)
        .where(in_window)
        .group_by(Agent.id, Agent.name, Agent.kind)
        .order_by(requests.desc(), Agent.name)
    )
    return [
        AgentUsage(
            agent_id=agent_id,
            name=name,
            kind=kind,
            requests=int(count),
            avg_latency_ms=rounded(latency),
            avg_tokens=rounded(tokens),
        )
        for agent_id, name, kind, count, latency, tokens in rows.tuples()
    ]


_STAGE_LATENCY_SQL = text(
    """
    SELECT t.key, avg((t.value #>> '{}')::double precision)
    FROM context_requests AS r
    CROSS JOIN LATERAL jsonb_each(r.timings) AS t(key, value)
    WHERE r.project_id = :project_id
      AND r.created_at >= :since
      AND r.status = 'succeeded'
      AND jsonb_typeof(t.value) = 'number'
    GROUP BY t.key
    """
)


async def _stage_latency(session: AsyncSession, project_id: uuid.UUID, since: datetime) -> dict[str, float]:
    rows = await session.execute(_STAGE_LATENCY_SQL, {"project_id": project_id, "since": since})
    return order_stages({str(key): rounded(avg) for key, avg in rows.tuples()})


async def _ingestion_metrics(
    session: AsyncSession, project_id: uuid.UUID, since: datetime
) -> IngestionMetrics:
    documents = await _count_by(session, Document.status, Document.project_id == project_id)
    jobs = await _count_by(session, IngestionJob.status, IngestionJob.project_id == project_id)
    duration_ms = func.extract("epoch", IngestionJob.finished_at - IngestionJob.started_at) * 1000
    avg_ingest = await session.scalar(
        select(func.avg(duration_ms)).where(
            IngestionJob.project_id == project_id,
            IngestionJob.kind == JobKind.ingest,
            IngestionJob.status == JobStatus.succeeded,
            IngestionJob.started_at.is_not(None),
            IngestionJob.finished_at >= since,
        )
    )
    return IngestionMetrics(
        documents_by_status={status: documents.get(status, 0) for status in DocumentStatus},
        jobs_by_status={status: jobs.get(status, 0) for status in JobStatus},
        avg_ingest_ms=rounded(avg_ingest),
    )


# --- Trace export (NDJSON) ----------------------------------------------------------------------------


async def count_requests(session: AsyncSession, project_id: uuid.UUID, since: datetime) -> int:
    return await _count(
        session,
        ContextRequest.id,
        ContextRequest.project_id == project_id,
        ContextRequest.created_at >= since,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _number(value: Decimal | float | int | None) -> float:
    return float(value) if value is not None else 0.0


def decision_record(decision: ContextDecision, *, clearance: int) -> dict[str, Any]:
    """One decision of a trace line; content above the exporter's clearance is redacted."""
    visible = int(decision.classification) <= clearance
    return {
        "candidate_type": str(decision.candidate_type),
        "candidate_id": decision.candidate_id if visible else None,
        "document_id": str(decision.document_id) if visible and decision.document_id else None,
        "memory_item_id": str(decision.memory_item_id) if visible and decision.memory_item_id else None,
        "title": decision.title if visible else None,
        "excerpt": decision.excerpt if visible else None,
        "source_kind": decision.source_kind,
        "classification": int(decision.classification),
        "scores": decision.scores or {},
        "included": bool(decision.included),
        "reason_code": str(decision.reason_code),
        "reason_detail": decision.reason_detail if visible else "",
        "tokens": int(decision.tokens),
        "rank": decision.rank,
        "citation": decision.citation,
        "redacted": not visible,
    }


def trace_record(
    request: ContextRequest,
    decisions: Sequence[ContextDecision],
    feedback: Sequence[ContextFeedback],
    *,
    clearance: int,
    agent: Agent | None = None,
    user_label: str | None = None,
    snapshot: tuple[str, int] | None = None,
) -> dict[str, Any]:
    """Self-contained evaluation record of one context request (FORGE export)."""
    decision_rows = [decision_record(d, clearance=clearance) for d in decisions]
    hidden_served = any(row["redacted"] and row["included"] for row in decision_rows)
    return {
        "schema": TRACE_SCHEMA,
        "request": {
            "id": str(request.id),
            "trace_id": request.trace_id,
            "created_at": _iso(request.created_at),
            "task": request.task,
            "intent": str(request.intent),
            "status": str(request.status),
            "error": request.error,
            "requested_by_type": str(request.requested_by_type),
            "agent": (
                {"id": str(agent.id), "name": agent.name, "kind": str(agent.kind)}
                if agent is not None
                else None
            ),
            "on_behalf_of": (
                {"id": str(request.user_id), "full_name": user_label} if request.user_id is not None else None
            ),
            "params": request.params or {},
            "latency_ms": int(request.latency_ms),
            "candidates_count": int(request.candidates_count),
            "included_count": int(request.included_count),
            "excluded_count": int(request.excluded_count),
            "tokens_used": int(request.tokens_used),
            "token_budget": int(request.token_budget),
            "cost_estimate": _number(request.cost_estimate),
            "snapshot": {"name": snapshot[0], "version": snapshot[1]} if snapshot else None,
        },
        "timings": request.timings or {},
        "context": REDACTED_CONTEXT if hidden_served else request.context_text,
        "decisions": decision_rows,
        "feedback": [
            {
                "id": str(f.id),
                "actor_type": str(f.actor_type),
                "actor_id": str(f.actor_id) if f.actor_id else None,
                "rating": int(f.rating),
                "comment": f.comment,
                "item_flags": f.item_flags or [],
                "created_at": _iso(f.created_at),
            }
            for f in feedback
        ],
    }


async def iter_trace_lines(
    project_id: uuid.UUID, *, since: datetime, clearance: int, batch_size: int = TRACE_EXPORT_BATCH
) -> AsyncIterator[bytes]:
    """Stream one NDJSON line per context request (oldest first), with its own database session."""
    async with get_sessionmaker()() as session:
        agents = {
            agent.id: agent
            for agent in await session.scalars(select(Agent).where(Agent.project_id == project_id))
        }
        user_labels: dict[uuid.UUID, str] = {}
        cursor: tuple[datetime, uuid.UUID] | None = None
        while True:
            stmt = (
                select(ContextRequest)
                .where(ContextRequest.project_id == project_id, ContextRequest.created_at >= since)
                .order_by(ContextRequest.created_at, ContextRequest.id)
                .limit(batch_size)
            )
            if cursor is not None:
                stmt = stmt.where(tuple_(ContextRequest.created_at, ContextRequest.id) > tuple_(*cursor))
            batch = list(await session.scalars(stmt))
            if not batch:
                break
            ids = [r.id for r in batch]

            decisions: dict[uuid.UUID, list[ContextDecision]] = defaultdict(list)
            for decision in await session.scalars(
                select(ContextDecision)
                .where(ContextDecision.request_id.in_(ids))
                .order_by(
                    ContextDecision.request_id,
                    ContextDecision.included.desc(),
                    ContextDecision.rank.asc().nulls_last(),
                    ContextDecision.id,
                )
            ):
                decisions[decision.request_id].append(decision)

            feedback: dict[uuid.UUID, list[ContextFeedback]] = defaultdict(list)
            for item in await session.scalars(
                select(ContextFeedback)
                .where(ContextFeedback.request_id.in_(ids))
                .order_by(ContextFeedback.created_at)
            ):
                feedback[item.request_id].append(item)

            snapshot_ids = {r.snapshot_id for r in batch if r.snapshot_id is not None}
            snapshots: dict[uuid.UUID, tuple[str, int]] = {}
            if snapshot_ids:
                rows = await session.execute(
                    select(ContextSnapshot.id, ContextSnapshot.name, ContextSnapshot.version).where(
                        ContextSnapshot.id.in_(snapshot_ids)
                    )
                )
                snapshots = {sid: (name, int(version)) for sid, name, version in rows.tuples()}

            missing_users = {r.user_id for r in batch if r.user_id is not None} - set(user_labels)
            if missing_users:
                user_labels.update(
                    await actor_labels(session, [(ActorType.user, uid) for uid in missing_users])
                )

            for request in batch:
                record = trace_record(
                    request,
                    decisions.get(request.id, []),
                    feedback.get(request.id, []),
                    clearance=clearance,
                    agent=agents.get(request.agent_id) if request.agent_id else None,
                    user_label=user_labels.get(request.user_id) if request.user_id else None,
                    snapshot=snapshots.get(request.snapshot_id) if request.snapshot_id else None,
                )
                yield orjson.dumps(record, option=orjson.OPT_APPEND_NEWLINE)
            cursor = (batch[-1].created_at, batch[-1].id)
            session.expunge_all()
            if len(batch) < batch_size:
                break
