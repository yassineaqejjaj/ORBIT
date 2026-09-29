"""``retrieve`` and ``fuse`` stages (ARCHITECTURE §9.2–9.3).

* In parallel: hybrid search (BM25 + k-NN fused with RRF by ``app.search.hybrid``) over chunks
  (top 40 each) and memory (top 30 each, organisation long-term memory included), the session turns
  (Valkey) when a ``session_id`` is given. The pre-selection filter is **the project only**:
  governance is applied afterwards so that every exclusion can be explained.
* Pinned items of the base snapshot (``chunk:<id>`` / ``memory:<lineage_id>``) are re-hydrated.
* **Hydration**: every hit is re-read from Postgres in a few batched queries (status, ACL,
  classification, dates, supersession, document title/version/uri/source kind) — the index payload is
  never trusted for governance.
* Degraded mode: when the search index (or the embedder) is unavailable, a PostgreSQL full-text
  search (``french`` configuration) replaces it so the platform stays operational.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.textutils import FRENCH_STOPWORDS, fold, unique_preserving
from app.enums import (
    ActorType,
    CandidateType,
    ChunkStatus,
    DocumentStatus,
    MemoryEventType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    SourceKind,
)
from app.governance.acl import DEFAULT_ACL
from app.governance.policy import (
    FORGOTTEN_STATUS,
    SUPERSEDED_STATUS,
    Candidate,
    ForgetInfo,
    SupersessionInfo,
)
from app.models import Agent, Chunk, Document, MemoryEvent, MemoryItem, Source, User
from app.search.tokens import estimate_tokens

logger = logging.getLogger("orbit.context.retrieval")

CHUNK_TOP_K = 40
MEMORY_TOP_K = 30
SESSION_TURNS_LIMIT = 20
RRF_K = 60
INDEX_TIMEOUT_SECONDS = 10.0
SESSION_TIMEOUT_SECONDS = 3.0
MAX_FALLBACK_TERMS = 16

DEGRADED_SEARCH_WARNING = (
    "Recherche dégradée : index de recherche indisponible, recherche plein texte PostgreSQL utilisée."
)
SESSION_UNAVAILABLE_WARNING = "Mémoire de session indisponible : les tours de session n'ont pas été pris en compte."

_WORD = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)


class RetrievalUnavailable(RuntimeError):
    """The search index cannot serve this request (fallback to Postgres)."""


# --- Raw hits ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class IndexHit:
    """One fused hit (from ``app.search.hybrid`` or the Postgres fallback)."""

    id: str
    rrf: float
    rrf_norm: float
    bm25: float | None = None
    bm25_rank: int | None = None
    dense: float | None = None
    dense_rank: int | None = None
    embedding: list[float] | None = None
    via: str = "hybrid"


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def hit_from_fused(fused: Any) -> IndexHit:
    """Adapt an ``app.search.hybrid.FusedHit`` (attribute access, tolerant to missing fields)."""
    source = getattr(fused, "source", None) or {}
    embedding = source.get("embedding") if isinstance(source, Mapping) else None
    vector = [float(x) for x in embedding] if isinstance(embedding, list) and embedding else None
    return IndexHit(
        id=str(fused.id),
        rrf=_as_float(getattr(fused, "rrf", None)) or 0.0,
        rrf_norm=max(0.0, min(1.0, _as_float(getattr(fused, "rrf_norm", None)) or 0.0)),
        bm25=_as_float(getattr(fused, "bm25_score", None)),
        bm25_rank=_as_int(getattr(fused, "bm25_rank", None)),
        dense=_as_float(getattr(fused, "dense_score", None)),
        dense_rank=_as_int(getattr(fused, "dense_rank", None)),
        embedding=vector,
    )


async def search_index(
    kind: str,
    query_text: str,
    query_vector: Sequence[float] | None,
    *,
    project_id: uuid.UUID,
    size_each: int,
    include_org_memory: bool,
) -> list[IndexHit]:
    """Hybrid search through ``app.search.hybrid`` (raises :class:`RetrievalUnavailable`)."""
    try:
        from app.search.hybrid import hybrid_search
    except ImportError as exc:
        raise RetrievalUnavailable("hybrid search module missing") from exc
    try:
        fused = await asyncio.wait_for(
            hybrid_search(
                kind,
                query_text,
                query_vector,
                project_id=str(project_id),
                size_each=size_each,
                include_org_memory=include_org_memory,
            ),
            timeout=INDEX_TIMEOUT_SECONDS,
        )
    except NotImplementedError as exc:
        raise RetrievalUnavailable("hybrid search not implemented") from exc
    except RetrievalUnavailable:
        raise
    except Exception as exc:
        raise RetrievalUnavailable(f"{type(exc).__name__}: {exc}") from exc
    return [hit_from_fused(h) for h in fused]


# --- Postgres full-text fallback --------------------------------------------------------------------


def fallback_tsquery(task: str) -> str | None:
    """OR-query of the task's content words for ``to_tsquery('french', …)`` (letters/digits only)."""
    words = []
    for token in _WORD.findall(task.lower()):
        if len(token) < 3 and not token.isdigit():
            continue
        if fold(token) in FRENCH_STOPWORDS:
            continue
        words.append(token)
    words = unique_preserving(words)[:MAX_FALLBACK_TERMS]
    return " | ".join(words) if words else None


def _rank_hits(rows: Sequence[tuple[Any, float]], via: str) -> list[IndexHit]:
    hits: list[IndexHit] = []
    for position, (item_id, rank) in enumerate(rows, start=1):
        rrf = 1.0 / (RRF_K + position)
        hits.append(IndexHit(id=str(item_id), rrf=rrf, rrf_norm=0.0, bm25=float(rank or 0.0), bm25_rank=position, via=via))
    top = max((h.rrf for h in hits), default=0.0)
    for h in hits:
        h.rrf_norm = h.rrf / top if top > 0 else 0.0
    return hits


_CHUNK_FTS = text(
    """
    SELECT c.id, ts_rank_cd(to_tsvector('french', coalesce(d.title, '') || ' ' || c.text_redacted), q) AS rank
    FROM chunks c
    JOIN documents d ON d.id = c.document_id,
         to_tsquery('french', :q) AS q
    WHERE c.project_id = :project_id
      AND to_tsvector('french', coalesce(d.title, '') || ' ' || c.text_redacted) @@ q
    ORDER BY rank DESC, c.id
    LIMIT :size
    """
)

_MEMORY_FTS = text(
    """
    SELECT m.id, ts_rank_cd(to_tsvector('french', m.title || ' ' || m.content), q) AS rank
    FROM memory_items m, to_tsquery('french', :q) AS q
    WHERE m.is_current
      AND (m.project_id = :project_id OR (:include_org AND m.project_id IS NULL AND m.scope = 'long_term'))
      AND to_tsvector('french', m.title || ' ' || m.content) @@ q
    ORDER BY rank DESC, m.id
    LIMIT :size
    """
)


async def fallback_search(
    session: AsyncSession,
    kind: str,
    task: str,
    *,
    project_id: uuid.UUID,
    size: int,
    include_org_memory: bool,
) -> list[IndexHit]:
    query = fallback_tsquery(task)
    if not query:
        return []
    if kind == "chunks":
        result = await session.execute(_CHUNK_FTS, {"q": query, "project_id": project_id, "size": size})
    else:
        result = await session.execute(
            _MEMORY_FTS,
            {"q": query, "project_id": project_id, "size": size, "include_org": include_org_memory},
        )
    return _rank_hits([(row[0], row[1]) for row in result.all()], via="fulltext")


# --- Hydrated rows ------------------------------------------------------------------------------------


@dataclass(slots=True)
class ChunkRow:
    chunk: Chunk
    document: Document
    source_kind: SourceKind
    forgotten_by_label: str | None = None


@dataclass(slots=True)
class MemoryRow:
    item: MemoryItem
    superseded_by: SupersessionInfo | None = None
    forgotten: ForgetInfo | None = None
    status_changed_at: datetime | None = None


@dataclass(slots=True)
class SessionTurnRow:
    id: str
    index: int
    role: str
    content: str
    at: datetime | None
    recency: float


@dataclass(slots=True)
class PinnedRef:
    """A snapshot item to re-inject (``INCLUDED_PINNED`` unless governance excludes it)."""

    key: str
    candidate_type: CandidateType
    id: str
    title: str


@dataclass(slots=True)
class RawRetrieval:
    chunk_hits: list[IndexHit] = field(default_factory=list)
    memory_hits: list[IndexHit] = field(default_factory=list)
    chunks: dict[str, ChunkRow] = field(default_factory=dict)
    memory_by_id: dict[str, MemoryRow] = field(default_factory=dict)
    #: requested id (hit or lineage) -> hydrated current row
    memory_resolution: dict[str, MemoryRow] = field(default_factory=dict)
    memory_by_lineage: dict[str, MemoryRow] = field(default_factory=dict)
    session_turns: list[SessionTurnRow] = field(default_factory=list)
    pinned: list[PinnedRef] = field(default_factory=list)
    pinned_label: str | None = None
    warnings: list[str] = field(default_factory=list)
    sources_used: dict[str, str] = field(default_factory=dict)


async def _session_turns(project_id: uuid.UUID, session_id: str) -> list[SessionTurnRow]:
    from app.memory.short_term import get_turns

    turns = await asyncio.wait_for(
        get_turns(project_id, session_id, limit=SESSION_TURNS_LIMIT), timeout=SESSION_TIMEOUT_SECONDS
    )
    total = len(turns)
    rows: list[SessionTurnRow] = []
    for index, turn in enumerate(turns, start=1):
        role = str(getattr(turn.role, "value", turn.role))
        rows.append(
            SessionTurnRow(
                id=f"{session_id}:{index}",
                index=index,
                role=role,
                content=str(turn.content or ""),
                at=turn.at,
                recency=0.5 + 0.5 * (index / total if total else 1.0),
            )
        )
    return rows


async def _labels(session: AsyncSession, user_ids: set[uuid.UUID], agent_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    labels: dict[uuid.UUID, str] = {}
    if user_ids:
        for uid, name, email in (
            await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(user_ids)))
        ).tuples():
            labels[uid] = name or email
    if agent_ids:
        for aid, name in (await session.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))).tuples():
            labels[aid] = name
    return labels


def _uuid_list(values: Iterable[str]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for value in values:
        try:
            result.append(uuid.UUID(str(value)))
        except (ValueError, TypeError):
            continue
    return result


async def hydrate_chunks(session: AsyncSession, project_id: uuid.UUID, ids: Iterable[str]) -> dict[str, ChunkRow]:
    chunk_ids = _uuid_list(ids)
    if not chunk_ids:
        return {}
    rows = await session.execute(
        select(Chunk, Document, Source.kind)
        .join(Document, Document.id == Chunk.document_id)
        .join(Source, Source.id == Document.source_id)
        .where(Chunk.id.in_(chunk_ids), Chunk.project_id == project_id)
    )
    result: dict[str, ChunkRow] = {}
    forgotten_by: set[uuid.UUID] = set()
    for chunk, document, kind in rows.tuples():
        result[str(chunk.id)] = ChunkRow(chunk=chunk, document=document, source_kind=SourceKind(kind))
        if document.forgotten_by is not None:
            forgotten_by.add(document.forgotten_by)
    if forgotten_by:
        labels = await _labels(session, forgotten_by, set())
        for row in result.values():
            if row.document.forgotten_by is not None:
                row.forgotten_by_label = labels.get(row.document.forgotten_by)
    return result


def _belongs(item: MemoryItem, project_id: uuid.UUID) -> bool:
    if item.project_id == project_id:
        return True
    return item.project_id is None and item.scope == MemoryScope.long_term


async def hydrate_memory(
    session: AsyncSession,
    project_id: uuid.UUID,
    ids: Iterable[str],
    lineages: Iterable[str] = (),
) -> tuple[dict[str, MemoryRow], dict[str, MemoryRow]]:
    """Hydrate memory hits (by item id) and pinned lineages, resolving each to the lineage's current
    version. Returns ``(requested key -> row, lineage_id -> row)``: keys are hit ids and lineage ids."""
    item_ids = _uuid_list(ids)
    lineage_ids = _uuid_list(lineages)
    if not item_ids and not lineage_ids:
        return {}, {}
    conditions = []
    if item_ids:
        conditions.append(MemoryItem.id.in_(item_ids))
    if lineage_ids:
        conditions.append(MemoryItem.lineage_id.in_(lineage_ids))
    fetched = list((await session.scalars(select(MemoryItem).where(or_(*conditions)))).all())
    by_id = {item.id: item for item in fetched if _belongs(item, project_id)}

    # Resolve every requested lineage to its current (or latest) version.
    requested_ids = set(item_ids)
    wanted_lineages = {item.lineage_id for item in by_id.values() if item.id in requested_ids}
    wanted_lineages |= set(lineage_ids)
    current_lineages = {item.lineage_id for item in by_id.values() if item.is_current}
    missing = wanted_lineages - current_lineages
    if missing:
        extra = await session.scalars(select(MemoryItem).where(MemoryItem.lineage_id.in_(missing)))
        for item in extra:
            if _belongs(item, project_id):
                by_id[item.id] = item
    current_by_lineage: dict[uuid.UUID, MemoryItem] = {}
    for item in by_id.values():
        best = current_by_lineage.get(item.lineage_id)
        if best is None or (item.is_current, item.version) > (best.is_current, best.version):
            current_by_lineage[item.lineage_id] = item

    rows_by_lineage = {lid: MemoryRow(item=item) for lid, item in current_by_lineage.items()}
    await _enrich_memory(session, list(rows_by_lineage.values()))

    requested: dict[str, MemoryRow] = {}
    for item_id in item_ids:
        item = by_id.get(item_id)
        if item is not None and item.lineage_id in rows_by_lineage:
            requested[str(item_id)] = rows_by_lineage[item.lineage_id]
    for lid in lineage_ids:
        if lid in rows_by_lineage:
            requested[str(lid)] = rows_by_lineage[lid]
    return requested, {str(lid): row for lid, row in rows_by_lineage.items()}


async def _enrich_memory(session: AsyncSession, rows: list[MemoryRow]) -> None:
    """Supersession target, forgetting actor/date and obsolescence date (batched)."""
    superseding_ids = {r.item.superseded_by_id for r in rows if r.item.superseded_by_id is not None}
    if superseding_ids:
        targets = {
            item.id: item
            for item in await session.scalars(select(MemoryItem).where(MemoryItem.id.in_(superseding_ids)))
        }
        for r in rows:
            target = targets.get(r.item.superseded_by_id) if r.item.superseded_by_id else None
            if target is not None:
                r.superseded_by = SupersessionInfo(
                    title=target.title, version=target.version, date=target.valid_from or target.created_at
                )

    flagged = {
        r.item.lineage_id: r
        for r in rows
        if r.item.status in (MemoryStatus.forgotten, MemoryStatus.obsolete)
    }
    if not flagged:
        return
    events = await session.execute(
        select(MemoryEvent.lineage_id, MemoryEvent.event, MemoryEvent.actor_type, MemoryEvent.actor_id, MemoryEvent.created_at)
        .where(
            MemoryEvent.lineage_id.in_(list(flagged)),
            MemoryEvent.event.in_([MemoryEventType.forgotten, MemoryEventType.obsoleted]),
        )
        .order_by(MemoryEvent.created_at.desc())
    )
    latest: dict[tuple[uuid.UUID, str], tuple[str, uuid.UUID | None, datetime]] = {}
    for lineage_id, event, actor_type, actor_id, created_at in events.tuples():
        key = (lineage_id, str(getattr(event, "value", event)))
        if key not in latest:
            latest[key] = (str(getattr(actor_type, "value", actor_type)), actor_id, created_at)
    user_ids = {a for (t, a, _) in latest.values() if t == ActorType.user.value and a is not None}
    agent_ids = {a for (t, a, _) in latest.values() if t == ActorType.agent.value and a is not None}
    labels = await _labels(session, user_ids, agent_ids)
    for lineage_id, r in flagged.items():
        if r.item.status == MemoryStatus.forgotten:
            info = latest.get((lineage_id, MemoryEventType.forgotten.value))
            if info is not None:
                actor_type, actor_id, at = info
                by = labels.get(actor_id) if actor_id else ("Système ORBIT" if actor_type == "system" else None)
                r.forgotten = ForgetInfo(at=at, by=by)
            else:
                r.forgotten = ForgetInfo(at=r.item.updated_at, by=None)
        else:
            info = latest.get((lineage_id, MemoryEventType.obsoleted.value))
            r.status_changed_at = info[2] if info is not None else r.item.updated_at


# --- Orchestration ------------------------------------------------------------------------------------


async def retrieve(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    task: str,
    query_vector: Sequence[float] | None,
    include_chunks: bool,
    include_memory: bool,
    include_org_memory: bool,
    session_id: str | None,
    pinned: Sequence[PinnedRef] = (),
    pinned_label: str | None = None,
) -> RawRetrieval:
    """Parallel index/session retrieval, Postgres fallback, then batched hydration."""
    raw = RawRetrieval(pinned=list(pinned), pinned_label=pinned_label)

    async def _nothing() -> list[Any]:
        return []

    chunk_task = (
        search_index(
            "chunks", task, query_vector, project_id=project_id, size_each=CHUNK_TOP_K, include_org_memory=False
        )
        if include_chunks
        else _nothing()
    )
    memory_task = (
        search_index(
            "memory",
            task,
            query_vector,
            project_id=project_id,
            size_each=MEMORY_TOP_K,
            include_org_memory=include_org_memory,
        )
        if include_memory
        else _nothing()
    )
    session_task = _session_turns(project_id, session_id) if session_id else _nothing()
    chunk_res, memory_res, session_res = await asyncio.gather(
        chunk_task, memory_task, session_task, return_exceptions=True
    )

    degraded = False
    for kind, res, top_k in (("chunks", chunk_res, CHUNK_TOP_K), ("memory", memory_res, MEMORY_TOP_K)):
        if isinstance(res, BaseException):
            if not isinstance(res, RetrievalUnavailable):
                logger.warning("Index search for %s failed unexpectedly: %r", kind, res)
            else:
                logger.info("Index search for %s unavailable (%s): Postgres full-text fallback", kind, res)
            degraded = True
            hits = await fallback_search(
                session, kind, task, project_id=project_id, size=top_k, include_org_memory=include_org_memory
            )
            raw.sources_used[kind] = "fulltext"
        else:
            hits = list(res)  # type: ignore[arg-type]
            raw.sources_used[kind] = "hybrid"
        if kind == "chunks":
            raw.chunk_hits = hits
        else:
            raw.memory_hits = hits
    if degraded:
        raw.warnings.append(DEGRADED_SEARCH_WARNING)

    if isinstance(session_res, BaseException):
        if not isinstance(session_res, NotImplementedError):
            logger.warning("Session turns unavailable for %s: %r", session_id, session_res)
        if session_id:
            raw.warnings.append(SESSION_UNAVAILABLE_WARNING)
    else:
        raw.session_turns = list(session_res)  # type: ignore[arg-type]

    pinned_chunk_ids = [p.id for p in raw.pinned if p.candidate_type == CandidateType.chunk]
    pinned_lineages = [p.id for p in raw.pinned if p.candidate_type == CandidateType.memory]
    raw.chunks = await hydrate_chunks(session, project_id, [h.id for h in raw.chunk_hits] + pinned_chunk_ids)
    raw.memory_resolution, raw.memory_by_lineage = await hydrate_memory(
        session, project_id, [h.id for h in raw.memory_hits], pinned_lineages
    )
    return raw


# --- Fuse: hydrated rows -> candidates -------------------------------------------------------------------


def chunk_candidate(row: ChunkRow) -> Candidate:
    chunk, document = row.chunk, row.document
    forgotten = (
        chunk.status == ChunkStatus.forgotten
        or document.status == DocumentStatus.forgotten
        or document.forgotten_at is not None
    )
    superseded = chunk.status == ChunkStatus.superseded or chunk.version < document.current_version
    status = FORGOTTEN_STATUS if forgotten else (SUPERSEDED_STATUS if superseded else ChunkStatus.active.value)
    text_served = chunk.text_redacted or ""
    return Candidate(
        candidate_type=CandidateType.chunk,
        id=str(chunk.id),
        title=document.title,
        text=text_served,
        classification=max(int(chunk.classification), int(document.classification)),
        acl_principals=list(chunk.acl_principals or DEFAULT_ACL),
        extra_acls=[list(document.acl_principals or DEFAULT_ACL)],
        status=status,
        date=document.source_updated_at,
        source_kind=row.source_kind,
        document_id=document.id,
        version=chunk.version,
        uri=document.uri,
        section=chunk.section,
        pii_redacted=bool(chunk.pii),
        superseded_by=SupersessionInfo(
            title=document.title, version=document.current_version, date=document.source_updated_at
        )
        if superseded
        else None,
        forgotten=ForgetInfo(at=document.forgotten_at, by=row.forgotten_by_label) if forgotten else None,
        tokens=estimate_tokens(text_served),
    )


def memory_candidate(row: MemoryRow) -> Candidate:
    item = row.item
    status = str(getattr(item.status, "value", item.status))
    return Candidate(
        candidate_type=CandidateType.memory,
        id=str(item.id),
        title=item.title,
        text=item.content or "",
        classification=int(item.classification),
        acl_principals=list(item.acl_principals or DEFAULT_ACL),
        status=status,
        date=item.valid_from or item.created_at,
        memory_item_id=item.id,
        memory_scope=MemoryScope(item.scope),
        memory_kind=MemoryKind(item.kind),
        subject_user_id=item.subject_user_id,
        session_id=item.session_id,
        expires_at=item.expires_at,
        valid_to=item.valid_to,
        lineage_id=item.lineage_id,
        version=item.version,
        confidence=float(item.confidence if item.confidence is not None else 0.7),
        is_org_memory=item.project_id is None,
        superseded_by=row.superseded_by,
        forgotten=row.forgotten,
        status_changed_at=row.status_changed_at,
        tokens=estimate_tokens(item.content or ""),
    )


def session_candidate(turn: SessionTurnRow, session_id: str) -> Candidate:
    role_labels = {"user": "Utilisateur", "agent": "Agent", "tool": "Outil"}
    return Candidate(
        candidate_type=CandidateType.session,
        id=turn.id,
        title=f"Session {session_id} · tour {turn.index} ({role_labels.get(turn.role, turn.role)})",
        text=turn.content,
        classification=0,
        acl_principals=list(DEFAULT_ACL),
        status="active",
        date=turn.at,
        session_id=session_id,
        memory_scope=MemoryScope.short_term,
        extra={"recency": turn.recency, "role": turn.role, "turn": turn.index},
        tokens=estimate_tokens(turn.content),
        retrieved_by={"session"},
    )


def _apply_hit(candidate: Candidate, hit: IndexHit) -> None:
    s = candidate.scores
    if hit.rrf_norm >= s.rrf_norm:
        s.rrf_norm = hit.rrf_norm
        s.rrf = hit.rrf
        s.bm25 = hit.bm25 if hit.bm25 is not None else s.bm25
        s.bm25_rank = hit.bm25_rank if hit.bm25_rank is not None else s.bm25_rank
        s.dense = hit.dense if hit.dense is not None else s.dense
        s.dense_rank = hit.dense_rank if hit.dense_rank is not None else s.dense_rank
    if hit.embedding and candidate.embedding is None:
        candidate.embedding = hit.embedding
    candidate.retrieved_by.add(hit.via)


def _ghost(ref: PinnedRef) -> Candidate:
    """Pinned item whose content no longer exists: explained as forgotten."""
    return Candidate(
        candidate_type=ref.candidate_type,
        id=ref.id,
        title="Contenu supprimé",
        text="",
        classification=0,
        acl_principals=list(DEFAULT_ACL),
        status=FORGOTTEN_STATUS,
        date=None,
        key=ref.key,
        forgotten=ForgetInfo(at=None, by=None),
    )


def fuse(raw: RawRetrieval, *, session_id: str | None) -> list[Candidate]:
    """Merge hits, pinned items and session turns into unique candidates (keyed by stable identity)."""
    by_key: dict[str, Candidate] = {}

    for hit in raw.chunk_hits:
        row = raw.chunks.get(hit.id)
        if row is None:  # index hit without a Postgres row (purged content): nothing to explain
            continue
        candidate = by_key.get(f"chunk:{hit.id}")
        if candidate is None:
            candidate = chunk_candidate(row)
            by_key[candidate.key] = candidate
        _apply_hit(candidate, hit)

    for hit in raw.memory_hits:
        row = raw.memory_resolution.get(hit.id)
        if row is None:
            continue
        key = f"memory:{row.item.lineage_id}"
        candidate = by_key.get(key)
        if candidate is None:
            candidate = memory_candidate(row)
            by_key[key] = candidate
        _apply_hit(candidate, hit)

    for ref in raw.pinned:
        candidate = by_key.get(ref.key)
        if candidate is None:
            if ref.candidate_type == CandidateType.chunk and ref.id in raw.chunks:
                candidate = chunk_candidate(raw.chunks[ref.id])
            elif ref.candidate_type == CandidateType.memory and ref.id in raw.memory_by_lineage:
                candidate = memory_candidate(raw.memory_by_lineage[ref.id])
            else:
                candidate = _ghost(ref)
            by_key[candidate.key] = candidate
        candidate.pinned = True
        candidate.pinned_label = raw.pinned_label
        candidate.retrieved_by.add("pinned")

    if session_id:
        for turn in raw.session_turns:
            candidate = session_candidate(turn, session_id)
            by_key.setdefault(candidate.key, candidate)

    return list(by_key.values())


def pinned_refs(items: Sequence[Mapping[str, Any]]) -> list[PinnedRef]:
    """Snapshot items -> pinned references (session turns are ephemeral and not re-injected)."""
    refs: list[PinnedRef] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get("key") or "")
        kind, _, ident = key.partition(":")
        if kind not in (CandidateType.chunk.value, CandidateType.memory.value) or not ident or key in seen:
            continue
        seen.add(key)
        refs.append(
            PinnedRef(key=key, candidate_type=CandidateType(kind), id=ident, title=str(item.get("title") or ""))
        )
    return refs


__all__ = [
    "DEGRADED_SEARCH_WARNING",
    "ChunkRow",
    "IndexHit",
    "MemoryRow",
    "PinnedRef",
    "RawRetrieval",
    "RetrievalUnavailable",
    "fuse",
    "pinned_refs",
    "retrieve",
]
