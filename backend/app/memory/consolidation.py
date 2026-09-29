"""Memory consolidation (ARCHITECTURE §8): session summaries, long-term promotion, deduplication.

* **Session closing** — the turns buffered in Valkey for an agent session (and the ``short_term`` items
  created during it) are condensed into one project ``summary`` item by extractive summarization
  (sentences scored by term frequency and decision/requirement markers, kept in chronological order,
  PII redacted). The summary cites the session as provenance, the consolidated ``short_term`` items
  become ``obsolete`` with a ``derived_from`` relation from the summary, and the Valkey buffer is
  cleared. Used by ``POST /sessions/{id}/close`` and by consolidation jobs for idle sessions.
* **Promotion** — validated project facts/constraints/requirements that were included in at least
  :data:`PROMOTE_MIN_RETRIEVALS` context packages over :data:`PROMOTE_WINDOW` become ``long_term``
  (new version, append-only).
* **Deduplication** — near-identical current items of the same kind (similarity > 0.93, no divergence
  marker) are merged: the most reliable one wins, the other is superseded by it and its provenance
  is copied to the winner.

Functions flush but never commit (the caller — router or worker — commits).
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import (
    ActorType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RelationNodeType,
    RelationType,
    TurnRole,
)
from app.governance.acl import merge_acls
from app.ingestion.pii import detect_pii, redact
from app.ingestion.queue import track_step
from app.memory import lifecycle, short_term
from app.memory.conflicts import conflict_winner, content_terms, fold
from app.models import (
    ContextDecision,
    ContextRequest,
    IngestionJob,
    MemoryItem,
    MemoryProvenance,
    Project,
    Relation,
)
from app.schemas.memory import MemoryIn, ProvenanceIn
from app.services import audit
from app.services import projects as project_service
from app.services.audit import Actor, ActorLike, AuditAction, resolve_actor

logger = logging.getLogger("orbit.memory.consolidation")

SUMMARY_MAX_SENTENCES = 8
SUMMARY_MAX_CHARS = 2400
SENTENCE_MAX_CHARS = 320
SUMMARY_TITLE_MAX = 90
SUMMARY_CONFIDENCE = 0.65
PROMOTE_MIN_RETRIEVALS = 5
PROMOTE_WINDOW = timedelta(days=30)
PROMOTABLE_KINDS = (MemoryKind.fact, MemoryKind.constraint, MemoryKind.requirement)
PROMOTED_TAG = "long-terme"
DEDUPE_THRESHOLD = 0.93
DEDUPE_POOL = 400
SESSION_TAGS = ["session", "consolidation-auto"]
OWNER_ONLY_ACL = "role:owner"

ROLE_LABELS: dict[TurnRole, str] = {
    TurnRole.user: "Utilisateur",
    TurnRole.agent: "Agent",
    TurnRole.tool: "Outil",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_MARKERS = re.compile(
    r"\b(d[ée]cid|d[ée]cision|retenu|valid|besoin|doit|doivent|obligatoire|contrainte|risque|"
    r"priorit|livr|objectif|conclu|action|prochaine [ée]tape|a faire|à faire|plan)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d")


@dataclass(slots=True)
class ConsolidationResult:
    sessions_closed: int = 0
    summaries_created: int = 0
    short_term_consolidated: int = 0
    promoted: int = 0
    deduplicated: int = 0
    summaries: list[MemoryItem] = field(default_factory=list)

    def counters(self) -> dict[str, int]:
        return {
            "sessions_closed": self.sessions_closed,
            "summaries_created": self.summaries_created,
            "short_term_consolidated": self.short_term_consolidated,
            "promoted": self.promoted,
            "deduplicated": self.deduplicated,
        }


# --- Extractive summary ----------------------------------------------------------------------------------


@dataclass(slots=True)
class _Sentence:
    position: int
    role: TurnRole
    text: str
    score: float = 0.0


def _sentences(role: TurnRole, content: str, start: int) -> list[_Sentence]:
    result: list[_Sentence] = []
    for raw in _SENTENCE_SPLIT.split(content or ""):
        text = " ".join(raw.split()).strip(" -•*")
        if len(text) < 12:
            continue
        if len(text) > SENTENCE_MAX_CHARS:
            text = text[: SENTENCE_MAX_CHARS - 1].rstrip() + "…"
        result.append(_Sentence(position=start + len(result), role=role, text=text))
    return result


def summarize_turns(
    turns: Sequence[short_term.Turn], extra: Sequence[str] = (), *, max_sentences: int = SUMMARY_MAX_SENTENCES
) -> list[str]:
    """Pick the most informative sentences of a session, in chronological order, prefixed by role."""
    sentences: list[_Sentence] = []
    for turn in turns:
        sentences.extend(_sentences(TurnRole(turn.role), turn.content, len(sentences)))
    for text in extra:
        sentences.extend(_sentences(TurnRole.agent, text, len(sentences)))
    if not sentences:
        return []
    frequencies: Counter[str] = Counter()
    terms_by_sentence: list[set[str]] = []
    for sentence in sentences:
        terms = content_terms(sentence.text)
        terms_by_sentence.append(terms)
        frequencies.update(terms)
    for sentence, terms in zip(sentences, terms_by_sentence, strict=True):
        if not terms:
            continue
        weight = sum(frequencies[t] for t in terms) / math.sqrt(len(terms))
        if _MARKERS.search(fold(sentence.text)):
            weight *= 1.6
        if _NUMBER.search(sentence.text):
            weight *= 1.15
        if sentence.role == TurnRole.user:
            weight *= 1.1
        elif sentence.role == TurnRole.tool:
            weight *= 0.7
        sentence.score = weight
    # The opening request is always kept: it frames the session.
    first = next((s for s in sentences if s.role == TurnRole.user), sentences[0])
    ranked = sorted((s for s in sentences if s is not first), key=lambda s: (-s.score, s.position))
    chosen: list[_Sentence] = [first]
    seen = {fold(first.text)}
    for sentence in ranked:
        if len(chosen) >= max_sentences:
            break
        key = fold(sentence.text)
        if key in seen or sentence.score <= 0:
            continue
        seen.add(key)
        chosen.append(sentence)
    chosen.sort(key=lambda s: s.position)
    return [f"{ROLE_LABELS[s.role]} : {s.text}" for s in chosen]


def _topic(turns: Sequence[short_term.Turn], fallback: str) -> str:
    for turn in turns:
        if TurnRole(turn.role) == TurnRole.user and turn.content.strip():
            text = " ".join(turn.content.split())
            break
    else:
        text = fallback
    text = text.rstrip(" .!?…")
    return text if len(text) <= 60 else text[:59].rstrip() + "…"


def _summary_content(
    session_id: str, turns: Sequence[short_term.Turn], lines: Sequence[str], items: Sequence[MemoryItem]
) -> str:
    header = f"Synthèse de la session « {session_id} »"
    if turns:
        start, end = turns[0].at, turns[-1].at
        header += f" — {len(turns)} tour(s) du {start:%d/%m/%Y %H:%M} au {end:%d/%m/%Y %H:%M} UTC"
    parts = [header + ".", ""]
    parts.extend(f"- {line}" for line in lines)
    if items:
        parts.append("")
        parts.append("Éléments mémorisés pendant la session :")
        parts.extend(f"- {item.title}" for item in items[:10])
    content = "\n".join(parts).strip()
    if len(content) > SUMMARY_MAX_CHARS:
        content = content[: SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    entities = detect_pii(content)
    return redact(content, entities) if entities else content


async def _session_items(session: AsyncSession, project_id: uuid.UUID, session_id: str) -> list[MemoryItem]:
    rows = await session.scalars(
        select(MemoryItem)
        .where(
            MemoryItem.project_id == project_id,
            MemoryItem.session_id == session_id,
            MemoryItem.scope == MemoryScope.short_term,
            MemoryItem.is_current.is_(True),
            MemoryItem.status.in_(lifecycle.ACTIVE_STATUSES),
        )
        .order_by(MemoryItem.created_at)
    )
    return list(rows)


async def close_session(
    session: AsyncSession,
    project_id: uuid.UUID,
    session_id: str,
    actor: ActorLike,
    *,
    turns: Sequence[short_term.Turn] | None = None,
    clear: bool = True,
) -> MemoryItem | None:
    """Consolidate one session into a project ``summary`` item (``None`` when there is nothing to keep).

    ``turns`` may be given when already loaded; otherwise they are read from Valkey (an unavailable
    Valkey only loses the turns, short-term items are still consolidated).
    """
    resolved = resolve_actor(actor)
    if turns is None:
        try:
            turns = await short_term.get_turns(project_id, session_id)
        except Exception as exc:
            logger.warning("Valkey unavailable while closing session %s: %s", session_id, exc)
            turns = []
    items = await _session_items(session, project_id, session_id)
    lines = summarize_turns(turns, [f"{item.title}. {item.content}" for item in items])
    summary: MemoryItem | None = None
    if lines:
        topic = _topic(turns, items[0].title if items else session_id)
        title = f"Résumé de session : {topic}"
        if len(title) > SUMMARY_TITLE_MAX:
            title = title[: SUMMARY_TITLE_MAX - 1].rstrip() + "…"
        content = _summary_content(session_id, turns, lines, items)
        classification = max((int(i.classification) for i in items), default=None)
        acl = _most_restrictive_acl(items)
        data = MemoryIn(
            scope=MemoryScope.project,
            kind=MemoryKind.summary,
            title=title,
            content=content,
            classification=classification,
            acl_principals=acl,
            tags=list(SESSION_TAGS),
            confidence=SUMMARY_CONFIDENCE,
            status=MemoryStatus.proposed.value,
            provenance=[
                ProvenanceIn(
                    source_label=f"Session {session_id}",
                    excerpt=content[:600],
                )
            ],
        )
        summary = await lifecycle.create_item(
            session, project_id=project_id, data=data, actor=resolved, detect=False, audit_entry=False
        )
        for item in items:
            session.add(
                Relation(
                    project_id=project_id,
                    src_type=RelationNodeType.memory,
                    src_id=summary.id,
                    rel_type=RelationType.derived_from,
                    dst_type=RelationNodeType.memory,
                    dst_id=item.id,
                    confidence=1.0,
                    detail=f"Consolidation de la session « {session_id} »",
                )
            )
    for item in items:
        await lifecycle.obsolete(
            session, item, resolved, reason=f"Consolidé dans le résumé de la session « {session_id} »"
        )
    await audit.record(
        session,
        project_id,
        resolved,
        AuditAction.session_close,
        "session",
        session_id,
        summary=(
            f"Clôture de la session « {session_id} » : résumé créé"
            if summary is not None
            else f"Clôture de la session « {session_id} » : rien à consolider"
        ),
        details={
            "turns": len(turns),
            "short_term_items": len(items),
            "summary_id": str(summary.id) if summary is not None else None,
        },
    )
    await session.flush()
    if clear:
        try:
            await short_term.clear_session(project_id, session_id)
        except Exception as exc:
            logger.warning("Could not clear Valkey buffer of session %s: %s", session_id, exc)
    return summary


def _most_restrictive_acl(items: Sequence[MemoryItem]) -> list[str] | None:
    """ACL of a summary: most restrictive combination of the consolidated items (owners if empty)."""
    if not items:
        return None
    merged = merge_acls([list(item.acl_principals or []) for item in items])
    return merged or [OWNER_ONLY_ACL]


# --- Consolidation job ------------------------------------------------------------------------------------


async def _close_idle_sessions(
    session: AsyncSession, project: Project, job: IngestionJob, result: ConsolidationResult, now: datetime
) -> None:
    payload = job.payload or {}
    only = str(payload["session_id"]) if payload.get("session_id") else None
    ttl = int(project_service.normalize_settings(project.settings)["short_term_ttl_hours"])
    threshold = now - short_term.idle_threshold(ttl)
    actor = Actor.system()
    live: dict[str, short_term.SessionInfo] = {}
    try:
        live = {info.session_id: info for info in await short_term.list_sessions(project.id)}
    except Exception as exc:
        logger.warning("Valkey unavailable during consolidation of project %s: %s", project.id, exc)
    to_close = [
        sid for sid, info in live.items() if (only is not None and sid == only) or info.updated_at < threshold
    ]
    # Sessions whose Valkey buffer already expired but whose short-term items are still active.
    orphan_rows = await session.execute(
        select(MemoryItem.session_id, func.max(MemoryItem.created_at))
        .where(
            MemoryItem.project_id == project.id,
            MemoryItem.scope == MemoryScope.short_term,
            MemoryItem.is_current.is_(True),
            MemoryItem.status.in_(lifecycle.ACTIVE_STATUSES),
            MemoryItem.session_id.is_not(None),
        )
        .group_by(MemoryItem.session_id)
    )
    for sid, last_created in orphan_rows.tuples():
        if sid is None or sid in live or sid in to_close:
            continue
        if (only is not None and sid == only) or (last_created is not None and last_created < threshold):
            to_close.append(sid)
    for sid in to_close:
        summary = await close_session(session, project.id, sid, actor)
        result.sessions_closed += 1
        if summary is not None:
            result.summaries_created += 1
            result.summaries.append(summary)


async def _promote_frequent(
    session: AsyncSession, project: Project, result: ConsolidationResult, now: datetime
) -> None:
    usage = (
        select(MemoryItem.lineage_id.label("lineage_id"), func.count(ContextDecision.id).label("uses"))
        .join(MemoryItem, MemoryItem.id == ContextDecision.memory_item_id)
        .join(ContextRequest, ContextRequest.id == ContextDecision.request_id)
        .where(
            MemoryItem.project_id == project.id,
            ContextDecision.included.is_(True),
            ContextRequest.created_at >= now - PROMOTE_WINDOW,
        )
        .group_by(MemoryItem.lineage_id)
        .having(func.count(ContextDecision.id) >= PROMOTE_MIN_RETRIEVALS)
    ).subquery()
    rows = await session.execute(
        select(MemoryItem, usage.c.uses)
        .join(usage, usage.c.lineage_id == MemoryItem.lineage_id)
        .where(
            MemoryItem.is_current.is_(True),
            MemoryItem.scope == MemoryScope.project,
            MemoryItem.status == MemoryStatus.validated,
            MemoryItem.kind.in_(PROMOTABLE_KINDS),
        )
    )
    actor = Actor.system()
    for item, uses in rows.tuples():
        tags = list(dict.fromkeys([*(item.tags or []), PROMOTED_TAG]))
        await lifecycle.new_version(
            session,
            item,
            {"scope": MemoryScope.long_term, "tags": tags},
            actor,
            reason=f"Promu en mémoire long terme : inclus dans {int(uses)} contextes sur 30 jours",
        )
        result.promoted += 1


async def _deduplicate(session: AsyncSession, project: Project, result: ConsolidationResult) -> None:
    rows = await session.scalars(
        select(MemoryItem)
        .where(
            MemoryItem.project_id == project.id,
            MemoryItem.is_current.is_(True),
            MemoryItem.scope.in_(lifecycle.RELATABLE_SCOPES),
            MemoryItem.status.in_(lifecycle.ACTIVE_STATUSES),
        )
        .order_by(MemoryItem.updated_at.desc())
        .limit(DEDUPE_POOL)
    )
    by_kind: dict[MemoryKind, list[MemoryItem]] = {}
    for item in rows:
        by_kind.setdefault(MemoryKind(item.kind), []).append(item)
    actor = Actor.system()
    merged: set[uuid.UUID] = set()
    for items in by_kind.values():
        for index, a in enumerate(items):
            if a.id in merged:
                continue
            for b in items[index + 1 :]:
                if b.id in merged or a.id in merged:
                    continue
                if (
                    a.subject_user_id != b.subject_user_id
                    or a.classification != b.classification
                    or sorted(a.acl_principals or []) != sorted(b.acl_principals or [])
                ):
                    continue  # merging would widen or narrow access: keep both
                duplicate, similarity = lifecycle.is_duplicate(
                    lifecycle.embedding_text(a), lifecycle.embedding_text(b), None, None, DEDUPE_THRESHOLD
                )
                if not duplicate:
                    continue
                winner = conflict_winner(a, b)
                loser = b if winner is a else a
                await _copy_provenance(session, loser, winner)
                await lifecycle.supersede(
                    session,
                    loser,
                    winner,
                    actor,
                    reason=(
                        f"Doublon consolidé dans « {winner.title[:80]} » "
                        f"(similarité {round(similarity * 100)} %)"
                    ),
                )
                merged.add(loser.id)
                result.deduplicated += 1


async def _copy_provenance(session: AsyncSession, source: MemoryItem, target: MemoryItem) -> None:
    existing = await session.execute(
        select(MemoryProvenance.document_id, MemoryProvenance.chunk_id, MemoryProvenance.source_label).where(
            MemoryProvenance.memory_item_id == target.id
        )
    )
    known = set(existing.tuples())
    rows = await session.scalars(select(MemoryProvenance).where(MemoryProvenance.memory_item_id == source.id))
    for row in rows:
        key = (row.document_id, row.chunk_id, row.source_label)
        if key in known:
            continue
        known.add(key)
        session.add(
            MemoryProvenance(
                memory_item_id=target.id,
                document_id=row.document_id,
                chunk_id=row.chunk_id,
                context_request_id=row.context_request_id,
                source_label=row.source_label,
                excerpt=row.excerpt,
            )
        )


async def run_consolidation(session: AsyncSession, job: IngestionJob) -> dict[str, int]:
    """Handler of ``consolidate`` jobs (one project). Records one job step per phase; flushes only."""
    result = ConsolidationResult()
    project = await session.get(Project, job.project_id)
    if project is None:
        async with track_step(session, job, "consolidate") as step:
            step.skip("Projet introuvable")
        return result.counters()
    now = utcnow()

    async with track_step(session, job, "sessions") as step:
        await _close_idle_sessions(session, project, job, result, now)
        step.detail = (
            f"{result.sessions_closed} session(s) clôturée(s), {result.summaries_created} résumé(s) créé(s)"
        )
    async with track_step(session, job, "promote") as step:
        await _promote_frequent(session, project, result, now)
        step.detail = f"{result.promoted} item(s) promu(s) en mémoire long terme"
    async with track_step(session, job, "dedupe") as step:
        await _deduplicate(session, project, result)
        step.detail = f"{result.deduplicated} doublon(s) fusionné(s)"

    actor = _job_actor(job)
    await audit.record(
        session,
        project.id,
        actor,
        AuditAction.memory_consolidate,
        "project",
        project.id,
        summary=(
            f"Consolidation mémoire : {result.sessions_closed} session(s) clôturée(s), "
            f"{result.promoted} promotion(s), {result.deduplicated} doublon(s) fusionné(s)"
        ),
        details=result.counters(),
    )
    await session.flush()
    logger.info("Memory consolidation of project %s: %s", project.id, result.counters())
    return result.counters()


def _job_actor(job: IngestionJob) -> Actor:
    data = (job.payload or {}).get("actor")
    if isinstance(data, dict) and data.get("type") in {t.value for t in ActorType}:
        try:
            actor_id = uuid.UUID(str(data["id"])) if data.get("id") else None
        except ValueError:
            actor_id = None
        return Actor(ActorType(data["type"]), actor_id, str(data.get("label") or ""))
    return Actor.system()


__all__ = [
    "ConsolidationResult",
    "close_session",
    "run_consolidation",
    "summarize_turns",
]
