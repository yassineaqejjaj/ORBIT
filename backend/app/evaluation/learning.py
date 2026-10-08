"""§E2 bounded learning of the ranking weights from feedback.

Signals (``ORBIT_RANKING_LEARNING_WINDOW`` = last 90 days of the project, evaluation requests excluded):

* 👍/👎 — a context rated ≥ 4 makes its served items *positive*, ≤ 2 *negative*; item flags
  (``irrelevant`` / ``wrong`` / ``outdated``) make the flagged item negative (manual exclusion);
* pins — items pinned through a base snapshot are positive;
* triage decisions — a proposal validated in the inbox is positive wherever it was served, a rejected
  (obsoleted) one negative.

Each served item carries its ranking signals (fused rank, dense similarity, freshness, type boost, term
overlap). The update is ``w += rate × (mean(positive) − mean(negative))`` per signal, then every weight is
clamped to ``default ± ORBIT_RANKING_LEARNING_MAX_DELTA`` and the vector renormalised (sum 1, clamped
again). Every change is journaled in ``ranking_weight_changes`` (before / after / signals) and audited;
a revert re-applies the ``before`` of a change as a new journal entry. Nothing changes below
``ORBIT_RANKING_LEARNING_MIN_SIGNALS`` signals.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.enums import MemoryEventType
from app.models import (
    ContextDecision,
    ContextFeedback,
    ContextRequest,
    MemoryEvent,
    MemoryItem,
    RankingWeightChange,
)
from app.services import audit
from app.services.audit import ActorLike, AuditAction, resolve_actor

WINDOW_DAYS = 90
MAX_DECISIONS = 5000
SIGNALS = ("rrf", "dense", "freshness", "type", "terms")
NEGATIVE_FLAGS = {"irrelevant", "wrong", "outdated"}


def defaults() -> dict[str, float]:
    from app.context import rerank

    return {
        "rrf": rerank.W_RRF,
        "dense": rerank.W_DENSE,
        "freshness": rerank.W_FRESHNESS,
        "type": rerank.W_TYPE,
        "terms": rerank.W_TERMS,
    }


def bounds() -> dict[str, tuple[float, float]]:
    delta = settings.ranking_learning_max_delta
    return {k: (max(0.0, v - delta), min(1.0, v + delta)) for k, v in defaults().items()}


def _clamp(weights: Mapping[str, float]) -> dict[str, float]:
    limits = bounds()
    return {k: min(limits[k][1], max(limits[k][0], float(weights.get(k, v)))) for k, v in defaults().items()}


def bounded(weights: Mapping[str, float]) -> dict[str, float]:
    """Projection on {default ± max_delta} ∩ {Σ = 1}: clamp, then spread the residual over the weights
    that are not at the relevant bound (water-filling), rounded to 4 decimals."""
    limits = bounds()
    values = _clamp(weights)
    for _ in range(20):
        residual = 1.0 - sum(values.values())
        if abs(residual) < 1e-9:
            break
        free = [
            k
            for k in values
            if (residual > 0 and values[k] < limits[k][1]) or (residual < 0 and values[k] > limits[k][0])
        ]
        if not free:
            break
        share = residual / len(free)
        for k in free:
            values[k] = min(limits[k][1], max(limits[k][0], values[k] + share))
    return {k: round(v, 4) for k, v in values.items()}


async def latest_change(session: AsyncSession, project_id: uuid.UUID) -> RankingWeightChange | None:
    return await session.scalar(
        select(RankingWeightChange)
        .where(RankingWeightChange.project_id == project_id)
        .order_by(RankingWeightChange.created_at.desc(), RankingWeightChange.id.desc())
        .limit(1)
    )


async def current_weights(session: AsyncSession, project_id: uuid.UUID) -> dict[str, float]:
    """Weights in force for the project (defaults when learning is off or nothing was learned)."""
    if not settings.ranking_learning:
        return defaults()
    change = await latest_change(session, project_id)
    return _clamp(change.after) if change is not None else defaults()


def _vector(decision: ContextDecision) -> dict[str, float]:
    scores = decision.scores or {}
    signals = (scores.get("meta") or {}).get("signals") or {}
    return {
        "rrf": float(signals.get("rrf_norm") or 0.0),
        "dense": float(scores.get("dense") or 0.0),
        "freshness": float(scores.get("freshness") or 0.0),
        "type": float(signals.get("type_boost") or 0.0),
        "terms": float(signals.get("term_overlap") or 0.0),
    }


def _mean(vectors: list[dict[str, float]]) -> dict[str, float]:
    if not vectors:
        return dict.fromkeys(SIGNALS, 0.0)
    return {k: sum(v[k] for v in vectors) / len(vectors) for k in SIGNALS}


def propose(
    current: Mapping[str, float], positive: list[dict[str, float]], negative: list[dict[str, float]]
) -> dict[str, float]:
    """One bounded update step (pure)."""
    pos, neg = _mean(positive), _mean(negative)
    rate = settings.ranking_learning_rate
    if not positive or not negative:
        # One-sided evidence: move towards (or away from) the observed profile relative to the average.
        ref = pos if positive else neg
        sign = 1.0 if positive else -1.0
        avg = sum(ref.values()) / len(SIGNALS)
        raw = {k: current[k] + sign * rate * (ref[k] - avg) for k in SIGNALS}
    else:
        raw = {k: current[k] + rate * (pos[k] - neg[k]) for k in SIGNALS}
    return bounded(raw)


async def collect_signals(
    session: AsyncSession, project_id: uuid.UUID
) -> tuple[list[dict[str, float]], list[dict[str, float]], dict[str, int]]:
    since = utcnow() - timedelta(days=WINDOW_DAYS)
    requests = {
        row.id: row
        for row in await session.scalars(
            select(ContextRequest).where(
                ContextRequest.project_id == project_id, ContextRequest.created_at >= since
            )
        )
        if not (row.params or {}).get("evaluation")
    }
    if not requests:
        return [], [], {"feedback": 0, "pins": 0, "triage": 0}
    decisions = list(
        await session.scalars(
            select(ContextDecision)
            .where(ContextDecision.request_id.in_(list(requests)), ContextDecision.included.is_(True))
            .limit(MAX_DECISIONS)
        )
    )
    by_request: dict[uuid.UUID, list[ContextDecision]] = {}
    for d in decisions:
        by_request.setdefault(d.request_id, []).append(d)
    labels: dict[uuid.UUID, int] = {}  # decision id -> +1 / -1 (flags override ratings)
    counts = {"feedback": 0, "pins": 0, "triage": 0}

    feedback = await session.scalars(
        select(ContextFeedback).where(ContextFeedback.request_id.in_(list(requests)))
    )
    flagged: dict[uuid.UUID, int] = {}
    for fb in feedback:
        counts["feedback"] += 1
        served = by_request.get(fb.request_id, [])
        if fb.rating >= 4 or fb.rating <= 2:
            for d in served:
                labels.setdefault(d.id, 1 if fb.rating >= 4 else -1)
        bad = {f.get("citation") for f in fb.item_flags or [] if f.get("flag") in NEGATIVE_FLAGS}
        for d in served:
            if d.citation in bad:
                flagged[d.id] = -1
    labels.update(flagged)

    for d in decisions:
        if ((d.scores or {}).get("meta") or {}).get("pinned"):
            counts["pins"] += 1
            labels.setdefault(d.id, 1)

    events = await session.execute(
        select(MemoryEvent.lineage_id, MemoryEvent.event)
        .join(MemoryItem, MemoryItem.id == MemoryEvent.memory_item_id)
        .where(
            MemoryItem.project_id == project_id,
            MemoryEvent.created_at >= since,
            MemoryEvent.event.in_([MemoryEventType.validated, MemoryEventType.obsoleted]),
        )
    )
    triage = {str(lineage): 1 if event == MemoryEventType.validated else -1 for lineage, event in events}
    for d in decisions:
        lineage = ((d.scores or {}).get("meta") or {}).get("lineage_id")
        if lineage and lineage in triage and d.id not in flagged:
            counts["triage"] += 1
            labels[d.id] = triage[lineage]

    vectors = {d.id: _vector(d) for d in decisions}
    positive = [vectors[i] for i, label in labels.items() if label > 0]
    negative = [vectors[i] for i, label in labels.items() if label < 0]
    return positive, negative, counts


async def learn(session: AsyncSession, project_id: uuid.UUID, actor: ActorLike) -> RankingWeightChange | None:
    """Run one learning step (flush; caller commits). ``None`` when not enough signals or no change."""
    positive, negative, counts = await collect_signals(session, project_id)
    total = len(positive) + len(negative)
    if total < settings.ranking_learning_min_signals:
        return None
    before = await current_weights(session, project_id)
    after = propose(before, positive, negative)
    if all(abs(after[k] - before[k]) < 1e-4 for k in SIGNALS):
        return None
    signals: dict[str, Any] = {**counts, "positive": len(positive), "negative": len(negative)}
    return await _record(session, project_id, actor, "learn", before, after, signals)


async def revert(
    session: AsyncSession, project_id: uuid.UUID, change: RankingWeightChange, actor: ActorLike
) -> RankingWeightChange:
    before = await current_weights(session, project_id)
    change.reverted_at = utcnow()
    return await _record(
        session, project_id, actor, "revert", before, _clamp(change.before), {}, reverts=change.id
    )


async def reset(session: AsyncSession, project_id: uuid.UUID, actor: ActorLike) -> RankingWeightChange:
    before = await current_weights(session, project_id)
    return await _record(session, project_id, actor, "reset", before, defaults(), {})


async def _record(
    session: AsyncSession,
    project_id: uuid.UUID,
    actor: ActorLike,
    reason: str,
    before: Mapping[str, float],
    after: Mapping[str, float],
    signals: dict[str, Any],
    *,
    reverts: uuid.UUID | None = None,
) -> RankingWeightChange:
    resolved = resolve_actor(actor)
    change = RankingWeightChange(
        project_id=project_id,
        reason=reason,
        before=dict(before),
        after=dict(after),
        signals=signals,
        reverts_id=reverts,
        actor_label=resolved.label,
        created_at=utcnow(),
    )
    session.add(change)
    await session.flush()
    labels = {"learn": "ajustés d'après les retours", "revert": "rétablis", "reset": "réinitialisés"}
    await audit.record(
        session,
        project_id,
        actor,
        AuditAction.ranking_weights_change,
        "ranking_weights",
        change.id,
        summary=f"Poids du classement {labels[reason]} : {_fmt(after)}",
        details={"before": dict(before), "after": dict(after), "signals": signals, "reverts": reverts},
    )
    return change


def _fmt(weights: Mapping[str, float]) -> str:
    return ", ".join(f"{k} {weights[k]:.3f}" for k in SIGNALS)


def as_tuple(weights: Mapping[str, float] | None) -> tuple[float, ...] | None:
    return None if weights is None else tuple(float(weights[k]) for k in SIGNALS)


def describe(changes: Iterable[RankingWeightChange]) -> list[dict[str, Any]]:
    return [
        {
            "id": c.id,
            "reason": c.reason,
            "before": c.before,
            "after": c.after,
            "signals": c.signals,
            "reverts_id": c.reverts_id,
            "reverted_at": c.reverted_at,
            "actor": c.actor_label,
            "created_at": c.created_at,
        }
        for c in changes
    ]


__all__ = [
    "bounded",
    "bounds",
    "collect_signals",
    "current_weights",
    "defaults",
    "learn",
    "propose",
    "revert",
]
