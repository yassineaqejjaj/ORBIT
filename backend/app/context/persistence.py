"""``persist`` stage and read models (ARCHITECTURE §9.9, §11, docs/API.md « Contexte »).

* ``context_requests`` row + one ``context_decisions`` row per candidate (included **and** excluded,
  with scores, rank, citation and the full — unredacted — reason, for audit and evaluation);
* reconstitution of a served ``ContextPackage`` from those rows for the Explorer history, with the
  non-leak rules applied for the *viewer* (``app.context.visibility``);
* paginated request history with agent/user labels and feedback rating;
* feedback (rating + per-citation flags; ``outdated`` on a memory item records an obsolescence
  proposal on that item).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.context.selection import Decision
from app.context.textutils import preview
from app.context.visibility import (
    FORGOTTEN_TEXT,
    REDACTED_ACL_DETAIL,
    RESTRICTED_TITLE,
    Viewer,
    Visibility,
    redact_markdown,
)
from app.enums import (
    GOVERNANCE_ORDER,
    CandidateType,
    ContextRequestStatus,
    FeedbackFlag,
    Intent,
    MemoryEventType,
    MemoryKind,
    MemoryScope,
    PrincipalKind,
    ReasonCode,
    SourceKind,
)
from app.errors import not_found, validation_error
from app.models import (
    Agent,
    ContextDecision,
    ContextFeedback,
    ContextRequest,
    ContextSnapshot,
    MemoryEvent,
    MemoryItem,
    User,
)
from app.schemas.agents import AgentRef
from app.schemas.common import Page, PageParams, make_page
from app.schemas.context import (
    ContextConfig,
    ContextItem,
    ContextRequestDetail,
    ContextRequestSummary,
    ContextSnapshotInfo,
    ContextTimings,
    ExcludedItem,
    FeedbackIn,
    ItemFlagView,
    Scores,
    SnapshotRef,
)
from app.schemas.context import (
    ContextFeedback as ContextFeedbackOut,
)
from app.schemas.users import UserRef
from app.services.audit import ActorLike, resolve_actor

logger = logging.getLogger("orbit.context.persistence")

EXCLUDED_EXCERPT_CHARS = 280
_SCORE_KEYS = ("bm25", "dense", "rrf", "rerank", "freshness", "final")


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def scores_of(decision: Decision) -> Scores:
    s = decision.candidate.scores
    return Scores(
        bm25=_round(s.bm25),
        dense=_round(s.dense),
        rrf=_round(s.rrf),
        rerank=_round(s.rerank),
        freshness=_round(s.freshness),
        final=_round(s.final) or 0.0,
    )


def excerpt_of(decision: Decision) -> str:
    """Served excerpt for included items; short preview for exclusions (never forgotten content)."""
    c = decision.candidate
    if c.is_forgotten:
        return FORGOTTEN_TEXT
    if decision.included:
        return decision.excerpt
    return preview(c.text, EXCLUDED_EXCERPT_CHARS)


def _meta(decision: Decision) -> dict[str, Any]:
    c = decision.candidate
    s = c.scores
    return {
        "memory_kind": c.memory_kind.value if c.memory_kind else None,
        "memory_scope": c.memory_scope.value if c.memory_scope else None,
        "uri": c.uri,
        "version": c.version,
        "date": c.date.isoformat() if c.date else None,
        "pii_redacted": c.pii_redacted,
        "related_citation": decision.related_citation,
        "redact": decision.verdict.redact,
        "forgotten": c.is_forgotten,
        "lineage_id": str(c.lineage_id) if c.lineage_id else None,
        "subject_user_id": str(c.subject_user_id) if c.subject_user_id else None,
        "acls": [list(acl or []) for acl in c.all_acls],
        "pinned": c.pinned,
        "retrieved_by": sorted(c.retrieved_by),
        "signals": {
            "rrf_norm": _round(s.rrf_norm),
            "bm25_rank": s.bm25_rank,
            "dense_rank": s.dense_rank,
            "cross_encoder": _round(s.cross_encoder),
            "type_boost": _round(s.type_boost),
            "term_overlap": _round(s.term_overlap),
        },
    }


def decision_row(request_id: uuid.UUID, decision: Decision) -> ContextDecision:
    c = decision.candidate
    scores = scores_of(decision).model_dump()
    scores["meta"] = _meta(decision)
    return ContextDecision(
        request_id=request_id,
        candidate_type=c.candidate_type,
        candidate_id=c.id,
        document_id=c.document_id,
        memory_item_id=c.memory_item_id,
        title=c.title,
        excerpt=excerpt_of(decision),
        source_kind=c.source_kind.value if c.source_kind else None,
        classification=max(0, min(3, int(c.classification))),
        scores=scores,
        included=decision.included,
        reason_code=decision.verdict.reason_code,
        reason_detail=decision.verdict.reason_detail,
        tokens=decision.tokens if decision.included else c.tokens,
        rank=decision.rank,
        citation=decision.citation,
    )


def cost_estimate(tokens_used: int) -> Decimal:
    return (Decimal(tokens_used) / Decimal(1000) * Decimal(str(settings.cost_per_1k_tokens))).quantize(
        Decimal("0.000001")
    )


# --- Views shared by the live response and the reconstitution ---------------------------------------


def excluded_view(
    viewer: Viewer,
    *,
    candidate_type: CandidateType,
    item_id: str | None,
    title: str,
    excerpt: str,
    source_kind: SourceKind | None,
    memory_kind: MemoryKind | None,
    classification: int,
    scores: Scores,
    reason_code: ReasonCode,
    reason_detail: str,
    related_citation: str | None,
    acls: Sequence[Sequence[str] | None],
    memory_scope: MemoryScope | str | None,
    subject_user_id: uuid.UUID | str | None,
    forgotten: bool,
) -> ExcludedItem:
    visibility = viewer.visibility(
        classification=classification, acls=acls, memory_scope=memory_scope, subject_user_id=subject_user_id
    )
    if forgotten:
        excerpt = FORGOTTEN_TEXT
    if visibility == Visibility.full:
        return ExcludedItem(
            candidate_type=candidate_type,
            id=item_id,
            title=title,
            excerpt=excerpt,
            source_kind=source_kind,
            memory_kind=memory_kind,
            classification=classification,
            scores=scores,
            reason_code=reason_code,
            reason_detail=reason_detail,
            redacted=False,
            related_citation=related_citation,
        )
    if visibility == Visibility.partial:
        return ExcludedItem(
            candidate_type=candidate_type,
            id=item_id,
            title=title,
            excerpt=None,
            source_kind=source_kind,
            memory_kind=memory_kind,
            classification=classification,
            scores=scores,
            reason_code=reason_code,
            reason_detail=reason_detail,
            redacted=False,
            related_citation=related_citation,
        )
    detail = REDACTED_ACL_DETAIL if reason_code == ReasonCode.EXCLUDED_ACL else reason_detail
    return ExcludedItem(
        candidate_type=candidate_type,
        reason_code=reason_code,
        reason_detail=detail,
        redacted=True,
        classification=classification if reason_code == ReasonCode.EXCLUDED_CLASSIFICATION else None,
    )


def excluded_from_decision(viewer: Viewer, decision: Decision) -> ExcludedItem:
    c = decision.candidate
    return excluded_view(
        viewer,
        candidate_type=c.candidate_type,
        item_id=c.id,
        title=c.title,
        excerpt=excerpt_of(decision),
        source_kind=c.source_kind,
        memory_kind=c.memory_kind,
        classification=int(c.classification),
        scores=scores_of(decision),
        reason_code=decision.verdict.reason_code,
        reason_detail=decision.verdict.reason_detail,
        related_citation=decision.related_citation,
        acls=c.all_acls,
        memory_scope=c.memory_scope,
        subject_user_id=c.subject_user_id,
        forgotten=c.is_forgotten,
    )


def item_from_decision(decision: Decision) -> ContextItem:
    c = decision.candidate
    return ContextItem(
        citation=decision.citation or "",
        candidate_type=c.candidate_type,
        id=c.id,
        document_id=c.document_id,
        memory_item_id=c.memory_item_id,
        title=c.title,
        source_kind=c.source_kind,
        memory_kind=c.memory_kind,
        memory_scope=c.memory_scope,
        uri=c.uri,
        version=c.version,
        excerpt=decision.excerpt,
        tokens=decision.tokens,
        scores=scores_of(decision),
        classification=int(c.classification),
        date=c.date,
        pii_redacted=c.pii_redacted,
        reason_code=decision.verdict.reason_code,
        reason_detail=decision.verdict.reason_detail,
    )


def restrict_item(item: ContextItem, visibility: Visibility) -> tuple[ContextItem, str | None]:
    """Apply the non-leak rules to an included item shown to a viewer.

    Returns the item as the viewer may see it and the text replacing its Markdown bullet / source
    line (``None`` when fully visible).
    """
    if visibility == Visibility.full:
        return item, None
    if visibility == Visibility.partial:
        return item.model_copy(update={"excerpt": ""}), f"{item.title} — {RESTRICTED_TITLE.lower()}"
    hidden = item.model_copy(
        update={
            "id": "",
            "title": RESTRICTED_TITLE,
            "excerpt": "",
            "document_id": None,
            "memory_item_id": None,
            "uri": None,
        }
    )
    return hidden, RESTRICTED_TITLE


def present_included(
    viewer: Viewer, decisions: Sequence[Decision], markdown: str
) -> tuple[list[ContextItem], str]:
    """Included items and Markdown of a live package as ``viewer`` may see them."""
    items: list[ContextItem] = []
    replacements: dict[str, str] = {}
    for d in decisions:
        c = d.candidate
        visibility = viewer.visibility(
            classification=int(c.classification),
            acls=c.all_acls,
            memory_scope=c.memory_scope,
            subject_user_id=c.subject_user_id,
        )
        item, replacement = restrict_item(item_from_decision(d), visibility)
        items.append(item)
        if replacement is not None and d.citation:
            replacements[d.citation] = replacement
    return items, redact_markdown(markdown, replacements)


def exclusion_summary(excluded: Sequence[Decision]) -> dict[ReasonCode, int]:
    summary: dict[ReasonCode, int] = {}
    for d in excluded:
        summary[d.verdict.reason_code] = summary.get(d.verdict.reason_code, 0) + 1
    return dict(sorted(summary.items(), key=lambda kv: kv[0].value))


# --- History ------------------------------------------------------------------------------------------


async def list_requests(
    session: AsyncSession, project_id: uuid.UUID, params: PageParams, *, agent_id: uuid.UUID | None = None
) -> Page[ContextRequestSummary]:
    conditions = [ContextRequest.project_id == project_id]
    if agent_id is not None:
        conditions.append(ContextRequest.agent_id == agent_id)
    total = int(
        await session.scalar(select(func.count()).select_from(ContextRequest).where(*conditions)) or 0
    )
    ratings = (
        select(ContextFeedback.request_id, func.avg(ContextFeedback.rating).label("rating"))
        .group_by(ContextFeedback.request_id)
        .subquery()
    )
    rows = await session.execute(
        select(ContextRequest, Agent, User, ContextSnapshot.name, ContextSnapshot.version, ratings.c.rating)
        .outerjoin(Agent, Agent.id == ContextRequest.agent_id)
        .outerjoin(User, User.id == ContextRequest.user_id)
        .outerjoin(ContextSnapshot, ContextSnapshot.id == ContextRequest.snapshot_id)
        .outerjoin(ratings, ratings.c.request_id == ContextRequest.id)
        .where(*conditions)
        .order_by(ContextRequest.created_at.desc(), ContextRequest.id.desc())
        .offset(params.offset)
        .limit(params.limit)
    )
    items = [
        ContextRequestSummary(
            id=req.id,
            trace_id=req.trace_id,
            task=req.task,
            intent=req.intent,
            agent=AgentRef(id=agent.id, name=agent.name, kind=agent.kind) if agent is not None else None,
            user=UserRef(id=user.id, full_name=user.full_name) if user is not None else None,
            latency_ms=req.latency_ms,
            tokens_used=req.tokens_used,
            token_budget=req.token_budget,
            included_count=req.included_count,
            excluded_count=req.excluded_count,
            candidates_count=req.candidates_count,
            snapshot=SnapshotRef(name=snap_name, version=snap_version) if snap_name is not None else None,
            rating=round(float(rating), 2) if rating is not None else None,
            created_at=req.created_at,
        )
        for req, agent, user, snap_name, snap_version, rating in rows.tuples()
    ]
    return make_page(items, total, params)


async def get_request(session: AsyncSession, project_id: uuid.UUID, request_id: uuid.UUID) -> ContextRequest:
    request = await session.get(ContextRequest, request_id)
    if request is None or request.project_id != project_id:
        raise not_found("Requête de contexte introuvable")
    return request


_EXCLUSION_ORDER = {code: index for index, code in enumerate(GOVERNANCE_ORDER)}


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _enum_or_none[E](enum_cls: type[E], value: Any) -> E | None:
    if value in (None, ""):
        return None
    try:
        return enum_cls(value)  # type: ignore[call-arg]
    except ValueError:
        return None


def _stored_scores(raw: Mapping[str, Any] | None) -> Scores:
    data = {k: raw.get(k) for k in _SCORE_KEYS if raw and raw.get(k) is not None}
    return Scores(**data)


async def reconstitute(
    session: AsyncSession, request: ContextRequest, viewer: Viewer
) -> ContextRequestDetail:
    """Rebuild the served package from stored decisions, as the viewer is allowed to see it."""
    decisions = list(
        (
            await session.scalars(
                select(ContextDecision)
                .where(ContextDecision.request_id == request.id)
                .order_by(ContextDecision.rank.asc().nulls_last(), ContextDecision.id)
            )
        ).all()
    )
    params = request.params or {}
    items: list[ContextItem] = []
    excluded: list[ExcludedItem] = []
    replacements: dict[str, str] = {}
    for row in decisions:
        meta = (row.scores or {}).get("meta") or {}
        acls = meta.get("acls") or []
        scope = meta.get("memory_scope")
        subject = meta.get("subject_user_id")
        source_kind = _enum_or_none(SourceKind, row.source_kind)
        memory_kind = _enum_or_none(MemoryKind, meta.get("memory_kind"))
        scores = _stored_scores(row.scores)
        if row.included:
            visibility = viewer.visibility(
                classification=row.classification, acls=acls, memory_scope=scope, subject_user_id=subject
            )
            stored = ContextItem(
                citation=row.citation or "",
                candidate_type=row.candidate_type,
                id=row.candidate_id,
                document_id=row.document_id,
                memory_item_id=row.memory_item_id,
                title=row.title,
                source_kind=source_kind,
                memory_kind=memory_kind,
                memory_scope=_enum_or_none(MemoryScope, scope),
                uri=meta.get("uri"),
                version=meta.get("version"),
                excerpt=row.excerpt,
                tokens=row.tokens,
                scores=scores,
                classification=row.classification,
                date=_parse_date(meta.get("date")),
                pii_redacted=bool(meta.get("pii_redacted")),
                reason_code=row.reason_code,
                reason_detail=row.reason_detail,
            )
            item, replacement = restrict_item(stored, visibility)
            items.append(item)
            if replacement is not None and row.citation:
                replacements[row.citation] = replacement
        else:
            excluded.append(
                excluded_view(
                    viewer,
                    candidate_type=row.candidate_type,
                    item_id=row.candidate_id,
                    title=row.title,
                    excerpt=row.excerpt,
                    source_kind=source_kind,
                    memory_kind=memory_kind,
                    classification=row.classification,
                    scores=scores,
                    reason_code=row.reason_code,
                    reason_detail=row.reason_detail,
                    related_citation=meta.get("related_citation"),
                    acls=acls,
                    memory_scope=scope,
                    subject_user_id=subject,
                    forgotten=bool(meta.get("forgotten")),
                )
            )
    items.sort(key=lambda i: int(i.citation[1:]) if i.citation[1:].isdigit() else 10_000)
    # Same order as the live package: governance order, then selection exclusions (stable: by rank).
    excluded.sort(key=lambda e: _EXCLUSION_ORDER.get(e.reason_code, len(_EXCLUSION_ORDER)))
    summary: dict[ReasonCode, int] = {}
    for row in decisions:
        if not row.included:
            summary[row.reason_code] = summary.get(row.reason_code, 0) + 1

    snapshot_info = None
    if request.snapshot_id is not None:
        snap = await session.get(ContextSnapshot, request.snapshot_id)
        if snap is not None:
            snapshot_info = ContextSnapshotInfo(id=snap.id, name=snap.name, version=snap.version)
    config_raw = params.get("config") or {}
    feedback_rows = (
        await session.scalars(
            select(ContextFeedback)
            .where(ContextFeedback.request_id == request.id)
            .order_by(ContextFeedback.created_at.desc())
        )
    ).all()
    timings = {k: v for k, v in (request.timings or {}).items() if k in ContextTimings.model_fields}
    return ContextRequestDetail(
        request_id=request.id,
        trace_id=request.trace_id,
        task=request.task,
        intent=request.intent,
        created_at=request.created_at,
        context=redact_markdown(request.context_text or "", replacements),
        items=items,
        excluded=excluded,
        exclusion_summary=dict(sorted(summary.items(), key=lambda kv: kv[0].value)),
        tokens_used=request.tokens_used,
        token_budget=request.token_budget,
        candidates_count=request.candidates_count,
        timings=ContextTimings(**timings),
        snapshot=snapshot_info,
        config=ContextConfig(
            retrieval=config_raw.get("retrieval", "hybrid-bm25-knn-rrf-v1"),
            reranker=config_raw.get("reranker", settings.reranker),
            embedding_model=config_raw.get("embedding_model", settings.embedding_model),
            llm=config_raw.get("llm"),
        ),
        warnings=list(params.get("warnings") or []),
        mode="progressive" if (params.get("request") or {}).get("mode") == "progressive" else "full",
        cache_prefix_hash=(params.get("cache") or {}).get("prefix_hash"),
        cache_prefix_tokens=int((params.get("cache") or {}).get("prefix_tokens") or 0),
        cache_prefix_reused=bool((params.get("cache") or {}).get("reused")),
        feedback=[
            ContextFeedbackOut(
                id=f.id,
                actor_type=f.actor_type,
                actor_id=f.actor_id,
                rating=f.rating,
                comment=f.comment,
                item_flags=[
                    ItemFlagView.model_validate(flag) for flag in (f.item_flags or []) if _valid_flag(flag)
                ],
                created_at=f.created_at,
            )
            for f in feedback_rows
        ],
    )


def _valid_flag(flag: Any) -> bool:
    return (
        isinstance(flag, Mapping)
        and bool(flag.get("citation"))
        and flag.get("flag") in FeedbackFlag.__members__
    )


# --- Feedback -----------------------------------------------------------------------------------------


async def record_feedback(
    session: AsyncSession,
    request: ContextRequest,
    body: FeedbackIn,
    *,
    actor: ActorLike,
    actor_kind: PrincipalKind,
) -> ContextFeedback:
    """Store feedback (flush). Unknown citations ⇒ 422. ``outdated`` flags on memory items record an
    obsolescence proposal event on the flagged item."""
    flags = list(body.item_flags or [])
    decisions: dict[str, ContextDecision] = {}
    if flags:
        rows = await session.scalars(
            select(ContextDecision).where(
                ContextDecision.request_id == request.id, ContextDecision.citation.is_not(None)
            )
        )
        decisions = {row.citation: row for row in rows if row.citation}
        unknown = sorted({f.citation for f in flags if f.citation not in decisions})
        if unknown:
            raise validation_error(f"Citation(s) inconnue(s) pour cette requête : {', '.join(unknown)}")
    resolved = resolve_actor(actor)
    feedback = ContextFeedback(
        request_id=request.id,
        actor_type=actor_kind,
        actor_id=resolved.id,
        rating=body.rating,
        comment=body.comment,
        item_flags=[{"citation": f.citation, "flag": f.flag.value} for f in flags],
    )
    session.add(feedback)
    await session.flush()
    for flag in flags:
        if flag.flag != FeedbackFlag.outdated:
            continue
        decision = decisions[flag.citation]
        if decision.memory_item_id is None:
            continue
        await _propose_obsolescence(session, request, decision, feedback, actor)
    return feedback


async def _propose_obsolescence(
    session: AsyncSession,
    request: ContextRequest,
    decision: ContextDecision,
    feedback: ContextFeedback,
    actor: ActorLike,
) -> None:
    item = await session.get(MemoryItem, decision.memory_item_id)
    if item is None:
        return
    if not item.is_current:
        current = await session.scalar(
            select(MemoryItem).where(
                MemoryItem.lineage_id == item.lineage_id, MemoryItem.is_current.is_(True)
            )
        )
        item = current or item
    reason = f"Signalé comme obsolète dans le feedback de la requête de contexte ({decision.citation})"
    data = {
        "proposal": True,
        "source": "context_feedback",
        "request_id": str(request.id),
        "feedback_id": str(feedback.id),
        "citation": decision.citation,
    }
    try:
        from app.memory.lifecycle import record_event

        await record_event(session, item, MemoryEventType.obsoleted, actor, reason=reason, data=data)
        return
    except (ImportError, NotImplementedError):
        logger.info("Memory lifecycle unavailable: obsolescence proposal stored directly")
    resolved = resolve_actor(actor)
    session.add(
        MemoryEvent(
            memory_item_id=item.id,
            lineage_id=item.lineage_id,
            event=MemoryEventType.obsoleted,
            actor_type=resolved.type,
            actor_id=resolved.id,
            reason=reason,
            data=data,
        )
    )
    await session.flush()


def request_row(
    *,
    request_id: uuid.UUID,
    project_id: uuid.UUID,
    trace_id: str,
    agent_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    requested_by_type: PrincipalKind,
    requested_by_id: uuid.UUID | None,
    task: str,
    intent: Intent,
    params: dict[str, Any],
    token_budget: int,
) -> ContextRequest:
    return ContextRequest(
        id=request_id,
        project_id=project_id,
        trace_id=trace_id,
        agent_id=agent_id,
        user_id=user_id,
        requested_by_type=requested_by_type,
        requested_by_id=requested_by_id,
        task=task,
        intent=intent,
        params=params,
        status=ContextRequestStatus.succeeded,
        token_budget=token_budget,
    )
