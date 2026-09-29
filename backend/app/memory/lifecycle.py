"""Memory lifecycle (ARCHITECTURE §8): creation, append-only versioning, validation, supersession,
contradiction detection, selective forgetting and periodic maintenance.

Rules:

* **Append-only versioning** — content changes (title, content, kind, tags, classification,
  validity, scope) create a new ``MemoryItem`` row with the same ``lineage_id`` and ``version + 1``;
  the previous row gets ``is_current = False``. Provenance rows are copied to the new version and
  references (relations, ``supersedes_id`` / ``superseded_by_id`` of other current items) are
  re-pointed to it, so every current row is self-contained. Status transitions (validate, obsolete,
  supersede, restore, forget) are lifecycle metadata: they update the current row in place and are
  traced by a ``MemoryEvent``. Every transition writes an event and an audit entry.
* **Supersession** — a newer decision (``valid_from`` later by more than one hour) supersedes an
  older validated/proposed decision of the same project when their similarity is > 0.80, or when it
  explicitly replaces it (« PWA *plutôt qu'une application native* », see
  :func:`app.memory.conflicts.replacement_phrase`). A *proposed* newer decision never silently
  replaces a *validated* one: a conflict is flagged instead and the supersession happens when the
  proposal is validated. Reversible with :func:`restore` (a restored pair is never auto-superseded
  again).
* **Contradiction** — similarity > 0.70 with divergence markers (negation, numeric values, antonyms)
  ⇒ relation ``contradicts`` + ``conflict_detected`` events on both items.
* **Selective forgetting** — tombstone, removal from the index (all versions), status ``forgotten``,
  content replaced by ``[oublié]`` in every version and provenance excerpt (title/metadata kept for
  audit), Valkey purge; documents: :func:`propagate_document_forget`.
* Derived items inherit the most restrictive ACL (:func:`app.governance.acl.merge_acls`) and the
  highest classification of their sources; user memory gets ACL ``user:<subject>``; short-term
  memory expires after the project's ``short_term_ttl_hours``.
* Agents can only create ``proposed`` items.

Similarity is the maximum of the embedding cosine and a lexical topic overlap
(:func:`app.memory.conflicts.topic_similarity`) so that detection keeps working when the embedding
model or the index is unavailable.

All functions flush but do not commit (the caller commits). Search-index writes are best effort:
failures are logged and never abort the database transaction (a reindex job repairs the index).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import (
    MEMORY_KIND_LABELS,
    ActorType,
    DocumentStatus,
    JobKind,
    JobStatus,
    MemoryEventType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RelationNodeType,
    RelationType,
    TombstoneTarget,
    classification_code,
)
from app.errors import conflict, validation_error
from app.governance.acl import merge_acls, user_principal
from app.memory import short_term
from app.memory.conflicts import cosine as cosine_similarity
from app.memory.conflicts import (
    divergences,
    duplicate_similarity,
    format_similarity,
    join_markers,
    kind_family,
    replacement_phrase,
    replacement_phrases,
    topic_similarity,
)
from app.models import (
    Chunk,
    ContextDecision,
    ContextRequest,
    Document,
    IngestionJob,
    MemoryEvent,
    MemoryItem,
    MemoryProvenance,
    Project,
    Relation,
    Tombstone,
)
from app.schemas.memory import MemoryIn, MemoryUpdateIn
from app.search import embeddings, opensearch
from app.services import audit
from app.services import projects as project_service
from app.services.audit import Actor, ActorLike, AuditAction, resolve_actor

logger = logging.getLogger("orbit.memory")

FORGOTTEN_CONTENT = "[oublié]"
SUPERSEDE_SIMILARITY = 0.80
CONFLICT_SIMILARITY = 0.70
#: Minimum similarity for an explicit replacement (« … plutôt qu'une application native »).
REPLACEMENT_MIN_SIMILARITY = 0.25
EXPLICIT_REPLACEMENT_CONFIDENCE = 0.9
#: Two items whose ``valid_from`` differ by less than this have no clear temporal order.
TEMPORAL_ORDER_MIN = timedelta(hours=1)
RELATION_CANDIDATES = 12
LEXICAL_CANDIDATE_POOL = 300
FORGET_CONFIDENCE_FACTOR = 0.6
MIN_CONFIDENCE = 0.05
LONG_TERM_DECAY_AFTER = timedelta(days=30)
LONG_TERM_DECAY_FACTOR = 0.95
LONG_TERM_MIN_CONFIDENCE = 0.2
LONG_TERM_DECAY_KINDS = (MemoryKind.fact, MemoryKind.constraint, MemoryKind.requirement, MemoryKind.decision)
MAINTENANCE_BATCH = 500
DEFAULT_CLASSIFICATION = 1
DEFAULT_CONFIDENCE = {MemoryStatus.validated: 0.8, MemoryStatus.proposed: 0.6}
#: Items created with this tag and scope ``long_term`` by a platform admin are organisation-wide.
ORG_MEMORY_TAG = "organisation"
MANUAL_SOURCE_LABEL = "Saisie manuelle"

ACTIVE_STATUSES: tuple[MemoryStatus, ...] = (MemoryStatus.proposed, MemoryStatus.validated)
RELATABLE_SCOPES: tuple[MemoryScope, ...] = (MemoryScope.project, MemoryScope.long_term)
VERSIONED_FIELDS: tuple[str, ...] = (
    "title",
    "content",
    "tags",
    "valid_from",
    "valid_to",
    "classification",
    "kind",
    "scope",
    "confidence",
)
_RELATION_FIELDS = ("title", "content", "kind")

STATUS_LABELS: dict[MemoryStatus, str] = {
    MemoryStatus.proposed: "proposé",
    MemoryStatus.validated: "validé",
    MemoryStatus.superseded: "remplacé",
    MemoryStatus.obsolete: "obsolète",
    MemoryStatus.forgotten: "oublié",
}


# --- Small helpers -----------------------------------------------------------------------------------


def _kind_label(kind: MemoryKind | str) -> str:
    return MEMORY_KIND_LABELS[MemoryKind(kind)].lower()


def _status_label(status: MemoryStatus | str) -> str:
    return STATUS_LABELS[MemoryStatus(status)]


def _quote(title: str, limit: int = 90) -> str:
    text = " ".join((title or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return f"« {text} »"


def _date_label(value: datetime | None) -> str:
    return value.date().isoformat() if value else "date inconnue"


def _json(value: Any) -> Any:
    """JSON-safe copy (uuids, enums, datetimes) for ``MemoryEvent.data``."""
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_json(v) for v in value]
    return str(value)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def embedding_text(item: MemoryItem | MemoryIn) -> str:
    """Text embedded for a memory item (title + content)."""
    return f"{item.title}\n{item.content}"


def relation_similarity(
    a_text: str, b_text: str, a_vector: Sequence[float] | None, b_vector: Sequence[float] | None
) -> float:
    """Similarity used for supersession/contradiction: max(embedding cosine, topic overlap)."""
    dense = cosine_similarity(a_vector, b_vector) if a_vector and b_vector else 0.0
    return max(dense, topic_similarity(a_text, b_text))


def is_active(item: MemoryItem) -> bool:
    return MemoryStatus(item.status) in ACTIVE_STATUSES


# --- Embeddings & index (best effort) --------------------------------------------------------------


async def embed_texts(texts: Sequence[str]) -> list[list[float]] | None:
    """Embed passages with the configured model; ``None`` when the model is unavailable."""
    if not texts:
        return []
    try:
        vectors = await embeddings.get_embedder().embed_documents(list(texts))
    except Exception as exc:
        logger.warning("Embedding unavailable for memory items (%s): lexical similarity only", exc)
        return None
    return [list(map(float, vector)) for vector in vectors]


def index_document(item: MemoryItem, vector: Sequence[float] | None) -> dict[str, Any]:
    """Memory index document (ARCHITECTURE §6)."""
    doc: dict[str, Any] = {
        "id": str(item.id),
        "title": item.title,
        "text": item.content,
        "classification": int(item.classification),
        "acl_principals": list(item.acl_principals or []),
        "status": MemoryStatus(item.status).value,
        "tags": list(item.tags or []),
        "created_at": item.created_at,
        "source_updated_at": item.valid_from,
        "lineage_id": str(item.lineage_id),
        "version": item.version,
        "is_current": bool(item.is_current),
        "scope": MemoryScope(item.scope).value,
        "kind": MemoryKind(item.kind).value,
        "subject_user_id": str(item.subject_user_id) if item.subject_user_id else None,
        "session_id": item.session_id,
        "valid_from": item.valid_from,
        "valid_to": item.valid_to,
        "expires_at": item.expires_at,
        "confidence": float(item.confidence),
        "supersedes_id": str(item.supersedes_id) if item.supersedes_id else None,
        "superseded_by_id": str(item.superseded_by_id) if item.superseded_by_id else None,
        "created_by_type": ActorType(item.created_by_type).value,
    }
    if item.project_id is not None:
        doc["project_id"] = str(item.project_id)
    if vector:
        doc["embedding"] = list(vector)
    return {key: (value.isoformat() if isinstance(value, datetime) else value) for key, value in doc.items()}


async def index_items(
    pairs: Sequence[tuple[MemoryItem, Sequence[float] | None]], *, refresh: bool = True
) -> None:
    """Upsert memory items in the memory index (computing missing vectors)."""
    if not pairs:
        return
    missing = [index for index, (_item, vector) in enumerate(pairs) if not vector]
    vectors: list[Sequence[float] | None] = [vector for _item, vector in pairs]
    if missing:
        computed = await embed_texts([embedding_text(pairs[i][0]) for i in missing])
        if computed:
            for position, vector in zip(missing, computed, strict=True):
                vectors[position] = vector
    docs = [index_document(item, vectors[i]) for i, (item, _v) in enumerate(pairs)]
    try:
        await opensearch.index_memory(docs, refresh=refresh)
    except Exception as exc:
        logger.warning("Memory indexing failed for %d item(s): %s", len(docs), exc)


async def _index_update(ids: Iterable[uuid.UUID], fields: Mapping[str, Any]) -> None:
    id_list = [str(i) for i in ids]
    if not id_list:
        return
    try:
        await opensearch.update_fields("memory", id_list, dict(fields), refresh=True)
    except Exception as exc:
        logger.warning("Memory index update failed (%s): %s", ", ".join(id_list), exc)


async def _index_delete(ids: Iterable[uuid.UUID]) -> None:
    id_list = [str(i) for i in ids]
    if not id_list:
        return
    try:
        await opensearch.delete_by_ids("memory", id_list, refresh=True)
    except Exception as exc:
        logger.warning("Memory index deletion failed (%s): %s", ", ".join(id_list), exc)


# --- Lookups -------------------------------------------------------------------------------------------


async def current_version(session: AsyncSession, lineage_id: uuid.UUID) -> MemoryItem | None:
    return await session.scalar(
        select(MemoryItem)
        .where(MemoryItem.lineage_id == lineage_id, MemoryItem.is_current.is_(True))
        .order_by(MemoryItem.version.desc())
        .limit(1)
    )


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> MemoryItem | None:
    """Item by id (any version), or the current version when ``item_id`` is a lineage id."""
    item = await session.get(MemoryItem, item_id)
    if item is not None:
        return item
    return await current_version(session, item_id)


async def ensure_current(session: AsyncSession, item: MemoryItem) -> MemoryItem:
    """Transitions always apply to the current version of the lineage."""
    if item.is_current:
        return item
    return await current_version(session, item.lineage_id) or item


async def _current_for_id(session: AsyncSession, item_id: uuid.UUID | None) -> MemoryItem | None:
    if item_id is None:
        return None
    item = await get_item(session, item_id)
    return await ensure_current(session, item) if item is not None else None


async def lineage_versions(session: AsyncSession, lineage_id: uuid.UUID) -> list[MemoryItem]:
    rows = await session.scalars(
        select(MemoryItem).where(MemoryItem.lineage_id == lineage_id).order_by(MemoryItem.version.desc())
    )
    return list(rows)


async def _provenance_floor(session: AsyncSession, item: MemoryItem) -> int:
    """Highest classification among the item's source chunks/documents (0 without sources)."""
    rows = await session.execute(
        select(
            func.max(func.coalesce(Chunk.classification, 0)),
            func.max(func.coalesce(Document.classification, 0)),
        )
        .select_from(MemoryProvenance)
        .outerjoin(Chunk, Chunk.id == MemoryProvenance.chunk_id)
        .outerjoin(Document, Document.id == MemoryProvenance.document_id)
        .where(MemoryProvenance.memory_item_id == item.id)
    )
    chunk_max, doc_max = rows.one()
    return max(int(chunk_max or 0), int(doc_max or 0))


# --- Events --------------------------------------------------------------------------------------------


async def record_event(
    session: AsyncSession,
    item: MemoryItem,
    event: MemoryEventType,
    actor: ActorLike,
    *,
    reason: str | None = None,
    data: Mapping[str, Any] | None = None,
) -> MemoryEvent:
    resolved = resolve_actor(actor)
    entry = MemoryEvent(
        memory_item_id=item.id,
        lineage_id=item.lineage_id,
        event=MemoryEventType(event),
        actor_type=resolved.type,
        actor_id=resolved.id,
        reason=reason,
        data=_json(dict(data or {})),
    )
    session.add(entry)
    return entry


async def _audit(
    session: AsyncSession,
    item: MemoryItem,
    actor: ActorLike,
    action: AuditAction,
    summary: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    payload = {"lineage_id": item.lineage_id, "version": item.version, "kind": item.kind, "scope": item.scope}
    payload.update(details or {})
    await audit.record(
        session, item.project_id, actor, action, "memory", item.id, summary=summary, details=payload
    )


# --- Creation ------------------------------------------------------------------------------------------


async def _ttl_hours(session: AsyncSession, project_id: uuid.UUID | None) -> int:
    project = await session.get(Project, project_id) if project_id else None
    settings_ = project_service.normalize_settings(project.settings if project else None)
    return int(settings_["short_term_ttl_hours"])


async def create_item(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None,
    data: MemoryIn,
    actor: ActorLike,
    force_status: str | None = None,
    vector: Sequence[float] | None = None,
    detect: bool = True,
    audit_entry: bool = True,
    refresh_index: bool = True,
) -> MemoryItem:
    """Create version 1 of a memory item (+ provenance rows, ``created`` event, indexing, relation
    detection). ``force_status="proposed"`` is used for agent callers (agents are always forced)."""
    resolved = resolve_actor(actor)
    now = utcnow()
    scope = MemoryScope(data.scope)
    kind = MemoryKind(data.kind)

    status = MemoryStatus(force_status or data.status or MemoryStatus.proposed)
    if resolved.type == ActorType.agent:
        status = MemoryStatus.proposed
    if status not in ACTIVE_STATUSES:
        raise validation_error("Un nouvel item mémoire doit être « proposé » ou « validé »")

    if project_id is None and scope != MemoryScope.long_term:
        raise validation_error("Seule la mémoire long terme peut être rattachée à l'organisation")

    # Provenance: resolve chunks/documents of the project.
    provenance_rows: list[MemoryProvenance] = []
    chunks: list[Chunk] = []
    documents: dict[uuid.UUID, Document] = {}
    for entry in data.provenance or []:
        if project_id is None and (entry.chunk_id or entry.document_id):
            raise validation_error("La mémoire d'organisation ne peut pas citer de document de projet")
        chunk = await session.get(Chunk, entry.chunk_id) if entry.chunk_id else None
        if entry.chunk_id and (chunk is None or chunk.project_id != project_id):
            raise validation_error("Fragment de source introuvable dans ce projet")
        document_id = entry.document_id or (chunk.document_id if chunk else None)
        document = None
        if document_id:
            document = documents.get(document_id) or await session.get(Document, document_id)
            if document is None or document.project_id != project_id:
                raise validation_error("Document source introuvable dans ce projet")
            if chunk is not None and chunk.document_id != document.id:
                raise validation_error("Le fragment cité n'appartient pas au document indiqué")
            if document.status == DocumentStatus.forgotten:
                raise validation_error("Impossible de dériver un item mémoire d'un document oublié")
            documents[document.id] = document
        if chunk is not None:
            chunks.append(chunk)
        excerpt = entry.excerpt or (chunk.text_redacted[:600] if chunk else "")
        label = entry.source_label or (
            f"{document.title} · §{chunk.ordinal + 1}"
            if document and chunk
            else (document.title if document else MANUAL_SOURCE_LABEL)
        )
        provenance_rows.append(
            MemoryProvenance(
                document_id=document_id, chunk_id=entry.chunk_id, source_label=label, excerpt=excerpt
            )
        )

    # Classification: highest of the declared level and the sources (derived content keeps its level).
    source_levels = [int(c.classification) for c in chunks] + [
        int(d.classification) for d in documents.values()
    ]
    if data.classification is not None:
        classification = max([int(data.classification), *source_levels])
    elif source_levels:
        classification = max(source_levels)
    else:
        classification = DEFAULT_CLASSIFICATION

    subject_user_id: uuid.UUID | None = None
    session_id: str | None = None
    expires_at: datetime | None = None
    if scope == MemoryScope.user:
        subject_user_id = data.subject_user_id or (resolved.id if resolved.type == ActorType.user else None)
        if subject_user_id is None:
            raise validation_error("« subject_user_id » est requis pour la mémoire utilisateur")
        acl = [user_principal(subject_user_id)]
    else:
        source_acls: list[Sequence[str] | None] = [c.acl_principals for c in chunks]
        source_acls += [d.acl_principals for d in documents.values()]
        acl = merge_acls([data.acl_principals, *source_acls])
        if not acl:
            logger.warning("Empty ACL intersection for a derived memory item: restricted to owners")
            acl = ["role:owner"]
    if scope == MemoryScope.short_term:
        if not data.session_id:
            raise validation_error("« session_id » est requis pour la mémoire court terme")
        session_id = data.session_id
        expires_at = now + timedelta(hours=await _ttl_hours(session, project_id))
        if data.valid_to is not None and data.valid_to < expires_at:
            expires_at = data.valid_to

    valid_from = data.valid_from or max(
        (d.source_updated_at for d in documents.values() if d.source_updated_at), default=now
    )
    confidence = data.confidence if data.confidence is not None else DEFAULT_CONFIDENCE[status]

    item = MemoryItem(
        project_id=project_id,
        lineage_id=uuid.uuid4(),
        version=1,
        is_current=True,
        scope=scope,
        kind=kind,
        status=status,
        title=" ".join(data.title.split()),
        content=data.content.strip(),
        confidence=_clamp(confidence),
        classification=classification,
        acl_principals=acl,
        tags=list(data.tags or []),
        subject_user_id=subject_user_id,
        session_id=session_id,
        expires_at=expires_at,
        valid_from=valid_from,
        valid_to=data.valid_to,
        created_by_type=resolved.type,
        created_by_id=resolved.id,
    )
    session.add(item)
    await session.flush()

    for row in provenance_rows:
        row.memory_item_id = item.id
        session.add(row)
    if project_id is not None:
        for document_id in documents:
            session.add(
                Relation(
                    project_id=project_id,
                    src_type=RelationNodeType.memory,
                    src_id=item.id,
                    rel_type=RelationType.derived_from,
                    dst_type=RelationNodeType.document,
                    dst_id=document_id,
                    confidence=1.0,
                    detail="Provenance",
                )
            )
    await record_event(
        session,
        item,
        MemoryEventType.created,
        resolved,
        data={
            "status": status,
            "scope": scope,
            "kind": kind,
            "classification": classification,
            "provenance": len(provenance_rows),
        },
    )
    if audit_entry:
        await _audit(
            session,
            item,
            resolved,
            AuditAction.memory_create,
            f"Création de {_quote(item.title)} ({_kind_label(kind)}, {_status_label(status)})",
            {"classification": classification, "provenance": len(provenance_rows)},
        )
    await session.flush()

    if vector is None:
        computed = await embed_texts([embedding_text(item)])
        vector = computed[0] if computed else None
    await index_items([(item, vector)], refresh=refresh_index)

    if data.supersedes_id:
        old = await _current_for_id(session, data.supersedes_id)
        if old is None or old.project_id != project_id:
            raise validation_error("L'item à remplacer est introuvable dans ce projet")
        await supersede(session, old, item, resolved, reason=None)
    elif detect:
        await detect_relations(session, item, vector=vector)
    return item


# --- Versioning ----------------------------------------------------------------------------------------


def _changes_dict(changes: MemoryUpdateIn | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(changes, MemoryUpdateIn):
        return changes.model_dump(exclude_unset=True)
    return dict(changes)


async def new_version(
    session: AsyncSession,
    item: MemoryItem,
    changes: MemoryUpdateIn | Mapping[str, Any],
    actor: ActorLike,
    *,
    reason: str | None = None,
    event: MemoryEventType = MemoryEventType.edited,
) -> MemoryItem:
    """Append a new version with ``changes`` applied; the previous version becomes non-current.

    Returns the current item unchanged when ``changes`` do not modify anything.
    """
    resolved = resolve_actor(actor)
    current = await ensure_current(session, item)
    if MemoryStatus(current.status) == MemoryStatus.forgotten:
        raise conflict("Impossible de modifier un item oublié")

    requested = _changes_dict(changes)
    unknown = set(requested) - set(VERSIONED_FIELDS)
    if unknown:
        raise validation_error(f"Champs non modifiables : {', '.join(sorted(unknown))}")

    diff: dict[str, dict[str, Any]] = {}
    values: dict[str, Any] = {}
    for field, value in requested.items():
        if value is None and field not in ("valid_to",):
            continue
        if field == "title":
            value = " ".join(str(value).split())
        elif field == "content":
            value = str(value).strip()
        elif field == "kind":
            value = MemoryKind(value)
        elif field == "scope":
            value = MemoryScope(value)
        elif field == "confidence":
            value = _clamp(value)
        elif field == "tags":
            value = list(value)
        old_value = getattr(current, field)
        if old_value != value:
            values[field] = value
            diff[field] = {"from": old_value, "to": value}
    if not values:
        return current

    if "classification" in values:
        floor = await _provenance_floor(session, current)
        if int(values["classification"]) < floor:
            raise validation_error(
                "La classification ne peut pas être inférieure à celle des sources "
                f"({classification_code(floor)})"
            )
    if values.get("scope") == MemoryScope.user or (
        "scope" in values and MemoryScope(current.scope) == MemoryScope.user
    ):
        raise validation_error("La portée « utilisateur » ne peut pas être modifiée")

    excluded = {"id", "created_at", "updated_at", "version", "is_current"}
    copied = {
        column.key: getattr(current, column.key)
        for column in MemoryItem.__table__.columns
        if column.key not in excluded
    }
    copied.update(values)
    new = MemoryItem(**copied, version=current.version + 1, is_current=True)
    current.is_current = False
    session.add(new)
    await session.flush()

    provenance = await session.scalars(
        select(MemoryProvenance).where(MemoryProvenance.memory_item_id == current.id)
    )
    for row in provenance:
        session.add(
            MemoryProvenance(
                memory_item_id=new.id,
                document_id=row.document_id,
                chunk_id=row.chunk_id,
                context_request_id=row.context_request_id,
                source_label=row.source_label,
                excerpt=row.excerpt,
            )
        )
    await session.execute(
        update(Relation)
        .where(Relation.src_type == RelationNodeType.memory, Relation.src_id == current.id)
        .values(src_id=new.id)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(Relation)
        .where(Relation.dst_type == RelationNodeType.memory, Relation.dst_id == current.id)
        .values(dst_id=new.id)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(MemoryItem)
        .where(MemoryItem.is_current.is_(True), MemoryItem.superseded_by_id == current.id)
        .values(superseded_by_id=new.id)
        .execution_options(synchronize_session="fetch")
    )
    await session.execute(
        update(MemoryItem)
        .where(MemoryItem.is_current.is_(True), MemoryItem.supersedes_id == current.id)
        .values(supersedes_id=new.id)
        .execution_options(synchronize_session="fetch")
    )

    truncated = {
        field: {
            side: (str(v)[:2000] if field == "content" and v is not None else v) for side, v in change.items()
        }
        for field, change in diff.items()
    }
    await record_event(
        session,
        new,
        event,
        resolved,
        reason=reason,
        data={"diff": truncated, "from_version": current.version, "version": new.version},
    )
    await _audit(
        session,
        new,
        resolved,
        AuditAction.memory_edit,
        f"Nouvelle version (v{new.version}) de {_quote(new.title)}",
        {"fields": sorted(diff)},
    )
    await session.flush()

    await _index_delete([current.id])
    computed = await embed_texts([embedding_text(new)])
    vector = computed[0] if computed else None
    await index_items([(new, vector)])
    if is_active(new) and set(values) & set(_RELATION_FIELDS):
        await detect_relations(session, new, vector=vector)
    return new


# --- Status transitions ---------------------------------------------------------------------------


async def validate(
    session: AsyncSession, item: MemoryItem, actor: ActorLike, reason: str | None = None
) -> MemoryItem:
    item = await ensure_current(session, item)
    status = MemoryStatus(item.status)
    if status == MemoryStatus.forgotten:
        raise conflict("Impossible de valider un item oublié")
    if status == MemoryStatus.validated:
        raise conflict("Cet item est déjà validé")
    if status != MemoryStatus.proposed:
        raise conflict(f"Un item {_status_label(status)} doit d'abord être restauré avant d'être validé")
    item.status = MemoryStatus.validated
    await record_event(
        session, item, MemoryEventType.validated, actor, reason=reason, data={"previous_status": status}
    )
    await _audit(session, item, actor, AuditAction.memory_validate, f"Validation de {_quote(item.title)}")
    await session.flush()
    await _index_update([item.id], {"status": item.status.value})
    # A validated decision may now replace older ones (pending proposals become effective).
    await detect_relations(session, item)
    return item


async def obsolete(session: AsyncSession, item: MemoryItem, actor: ActorLike, reason: str) -> MemoryItem:
    item = await ensure_current(session, item)
    status = MemoryStatus(item.status)
    if status == MemoryStatus.forgotten:
        raise conflict("Impossible de marquer obsolète un item oublié")
    if status not in ACTIVE_STATUSES:
        raise conflict(f"Cet item est déjà {_status_label(status)}")
    valid_to_set = item.valid_to is None
    if valid_to_set:
        item.valid_to = utcnow()
    item.status = MemoryStatus.obsolete
    await record_event(
        session,
        item,
        MemoryEventType.obsoleted,
        actor,
        reason=reason,
        data={"previous_status": status, "valid_to_set": valid_to_set},
    )
    await _audit(
        session,
        item,
        actor,
        AuditAction.memory_obsolete,
        f"{_quote(item.title)} marqué obsolète",
        {"reason": reason},
    )
    await session.flush()
    await _index_update([item.id], {"status": item.status.value, "valid_to": item.valid_to})
    return item


async def _relation_between(
    session: AsyncSession, a: uuid.UUID, b: uuid.UUID, rel_type: RelationType, *, both_ways: bool
) -> Relation | None:
    pairs = [and_(Relation.src_id == a, Relation.dst_id == b)]
    if both_ways:
        pairs.append(and_(Relation.src_id == b, Relation.dst_id == a))
    return await session.scalar(select(Relation).where(Relation.rel_type == rel_type, or_(*pairs)).limit(1))


async def _apply_supersession(
    session: AsyncSession,
    old: MemoryItem,
    new: MemoryItem,
    actor: ActorLike,
    *,
    reason_old: str,
    reason_new: str,
    confidence: float,
    detail: str,
    auto: bool,
) -> Relation:
    previous = MemoryStatus(old.status)
    valid_to_set = old.valid_to is None
    old.status = MemoryStatus.superseded
    old.superseded_by_id = new.id
    new.supersedes_id = old.id
    if valid_to_set:
        old.valid_to = new.valid_from if new.valid_from and new.valid_from > old.valid_from else utcnow()

    # A supersession resolves any pending contradiction between the two items.
    await session.execute(
        delete(Relation)
        .where(
            Relation.rel_type == RelationType.contradicts,
            or_(
                and_(Relation.src_id == old.id, Relation.dst_id == new.id),
                and_(Relation.src_id == new.id, Relation.dst_id == old.id),
            ),
        )
        .execution_options(synchronize_session=False)
    )
    relation = await _relation_between(session, new.id, old.id, RelationType.supersedes, both_ways=False)
    if relation is None:
        relation = Relation(
            project_id=new.project_id or old.project_id,
            src_type=RelationNodeType.memory,
            src_id=new.id,
            rel_type=RelationType.supersedes,
            dst_type=RelationNodeType.memory,
            dst_id=old.id,
            confidence=round(_clamp(confidence), 3),
            detail=detail,
        )
        session.add(relation)
    await record_event(
        session,
        old,
        MemoryEventType.superseded,
        actor,
        reason=reason_old,
        data={
            "role": "old",
            "by_id": new.id,
            "by_lineage_id": new.lineage_id,
            "by_title": new.title,
            "previous_status": previous,
            "valid_to_set": valid_to_set,
            "auto": auto,
            "confidence": round(_clamp(confidence), 3),
        },
    )
    await record_event(
        session,
        new,
        MemoryEventType.superseded,
        actor,
        reason=reason_new,
        data={
            "role": "new",
            "old_id": old.id,
            "old_lineage_id": old.lineage_id,
            "old_title": old.title,
            "auto": auto,
        },
    )
    await _audit(
        session,
        old,
        actor,
        AuditAction.memory_supersede,
        f"{_quote(old.title)} remplacé par {_quote(new.title)}",
        {"by_id": new.id, "auto": auto, "detail": detail},
    )
    await session.flush()
    await _index_update(
        [old.id], {"status": old.status.value, "superseded_by_id": new.id, "valid_to": old.valid_to}
    )
    await _index_update([new.id], {"supersedes_id": old.id})
    return relation


async def supersede(
    session: AsyncSession, old: MemoryItem, new: MemoryItem, actor: ActorLike, reason: str | None = None
) -> MemoryItem:
    """Mark ``old`` as superseded by ``new`` (relation + events on both). Returns ``old``."""
    old = await ensure_current(session, old)
    new = await ensure_current(session, new)
    if old.lineage_id == new.lineage_id:
        raise conflict("Un item ne peut pas se remplacer lui-même")
    if MemoryStatus.forgotten in (MemoryStatus(old.status), MemoryStatus(new.status)):
        raise conflict("Impossible de remplacer un item oublié ou de le remplacer par un item oublié")
    if not is_active(old):
        raise conflict(
            f"Seul un item proposé ou validé peut être remplacé (statut actuel : {_status_label(old.status)})"
        )
    if not is_active(new):
        raise conflict("L'item de remplacement doit être proposé ou validé")
    if old.project_id != new.project_id:
        raise validation_error("Les deux items doivent appartenir au même périmètre (projet)")
    await _apply_supersession(
        session,
        old,
        new,
        actor,
        reason_old=reason or f"Remplacé par {_quote(new.title)}",
        reason_new=reason or f"Remplace {_quote(old.title)}",
        confidence=1.0,
        detail=reason or "Remplacement manuel",
        auto=False,
    )
    return old


async def restore(
    session: AsyncSession, item: MemoryItem, actor: ActorLike, reason: str | None = None
) -> MemoryItem:
    """Undo supersession/obsolescence (back to ``validated`` or ``proposed``)."""
    item = await ensure_current(session, item)
    status = MemoryStatus(item.status)
    if status == MemoryStatus.forgotten:
        raise conflict("Un item oublié ne peut pas être restauré")
    if status not in (MemoryStatus.superseded, MemoryStatus.obsolete):
        raise conflict("Seul un item remplacé ou obsolète peut être restauré")

    trigger = MemoryEventType.superseded if status == MemoryStatus.superseded else MemoryEventType.obsoleted
    events = await session.scalars(
        select(MemoryEvent)
        .where(MemoryEvent.lineage_id == item.lineage_id, MemoryEvent.event == trigger)
        .order_by(MemoryEvent.created_at.desc())
    )
    last = next((e for e in events if (e.data or {}).get("role") != "new"), None)
    previous_raw = (last.data or {}).get("previous_status") if last else None
    if previous_raw in (MemoryStatus.proposed.value, MemoryStatus.validated.value):
        previous = MemoryStatus(previous_raw)
    else:
        was_validated = await session.scalar(
            select(func.count())
            .select_from(MemoryEvent)
            .where(MemoryEvent.lineage_id == item.lineage_id, MemoryEvent.event == MemoryEventType.validated)
        )
        previous = MemoryStatus.validated if was_validated else MemoryStatus.proposed

    cleared_lineage: uuid.UUID | None = None
    if status == MemoryStatus.superseded:
        replacing = await _current_for_id(session, item.superseded_by_id)
        item.superseded_by_id = None
        if replacing is not None:
            if replacing.supersedes_id == item.id:
                replacing.supersedes_id = None
            await session.execute(
                delete(Relation)
                .where(
                    Relation.rel_type == RelationType.supersedes,
                    Relation.src_id == replacing.id,
                    Relation.dst_id == item.id,
                )
                .execution_options(synchronize_session=False)
            )
            await record_event(
                session,
                replacing,
                MemoryEventType.restored,
                actor,
                reason=f"Le remplacement de {_quote(item.title)} a été annulé",
                data={"role": "replacement_cleared", "item_id": item.id, "item_lineage_id": item.lineage_id},
            )
            cleared_lineage = replacing.lineage_id
            await _index_update([replacing.id], {"supersedes_id": None})
    if last is not None and (last.data or {}).get("valid_to_set"):
        item.valid_to = None
    item.status = previous
    await record_event(
        session,
        item,
        MemoryEventType.restored,
        actor,
        reason=reason or "Restauration",
        data={"status": previous, "from_status": status, "cleared_supersession_by": cleared_lineage},
    )
    await _audit(
        session,
        item,
        actor,
        AuditAction.memory_restore,
        f"Restauration de {_quote(item.title)} ({_status_label(previous)})",
        {"from_status": status, "reason": reason},
    )
    await session.flush()
    await _index_update(
        [item.id], {"status": item.status.value, "superseded_by_id": None, "valid_to": item.valid_to}
    )
    return item


async def forget(session: AsyncSession, item: MemoryItem, actor: ActorLike, reason: str) -> MemoryItem:
    """Selective forgetting of a whole lineage (tombstone + propagation, see module docstring)."""
    resolved = resolve_actor(actor)
    item = await ensure_current(session, item)
    if MemoryStatus(item.status) == MemoryStatus.forgotten:
        raise conflict("Cet item a déjà été oublié")
    now = utcnow()
    original_content, original_title = item.content, item.title
    previous = MemoryStatus(item.status)

    versions = await lineage_versions(session, item.lineage_id)
    version_ids = [version.id for version in versions]
    for version in versions:
        version.content = FORGOTTEN_CONTENT
    item.status = MemoryStatus.forgotten
    if item.valid_to is None or item.valid_to > now:
        item.valid_to = now
    await session.execute(
        update(MemoryProvenance)
        .where(MemoryProvenance.memory_item_id.in_(version_ids))
        .values(excerpt=FORGOTTEN_CONTENT)
        .execution_options(synchronize_session=False)
    )
    if item.project_id is not None:
        session.add(
            Tombstone(
                project_id=item.project_id,
                target_type=TombstoneTarget.memory,
                target_id=item.id,
                reason=reason,
                requested_by=resolved.id if resolved.type == ActorType.user else None,
                propagated_at=now,
            )
        )

    purged = 0
    if item.project_id is not None:
        needles = [original_content]
        if len(original_title) >= 15:
            needles.append(original_title)
        for needle in needles:
            try:
                purged += await short_term.purge_matching(item.project_id, needle)
            except Exception as exc:
                logger.warning("Valkey purge failed while forgetting memory %s: %s", item.id, exc)

    await record_event(
        session,
        item,
        MemoryEventType.forgotten,
        resolved,
        reason=reason,
        data={"previous_status": previous, "versions": len(versions), "purged_turns": purged},
    )
    await _audit(
        session,
        item,
        resolved,
        AuditAction.memory_forget,
        f"Oubli sélectif de {_quote(original_title)}",
        {"reason": reason, "versions": len(versions), "purged_turns": purged},
    )
    await session.flush()
    await _index_delete(version_ids)
    return item


# --- Relation detection ---------------------------------------------------------------------------


def _hit_ids(hits: Iterable[opensearch.OSHit]) -> set[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    for hit in hits:
        try:
            ids.add(uuid.UUID(str(hit.id)))
        except ValueError:
            continue
    return ids


async def _relation_candidates(
    session: AsyncSession, item: MemoryItem, vector: Sequence[float] | None
) -> list[MemoryItem]:
    """Current active items of the same project and kind family that may relate to ``item``.

    Union of the k-NN neighbours (memory index), BM25 matches of explicit replacement phrases and a
    lexical shortlist from Postgres (robust to index lag or unavailability).
    """
    family = sorted(kind.value for kind in kind_family(item.kind))
    base = [
        MemoryItem.project_id == item.project_id,
        MemoryItem.is_current.is_(True),
        MemoryItem.lineage_id != item.lineage_id,
        MemoryItem.status.in_(ACTIVE_STATUSES),
        MemoryItem.scope.in_(RELATABLE_SCOPES),
        MemoryItem.kind.in_(family),
    ]
    search_ids: set[uuid.UUID] = set()
    filters = [
        {"terms": {"kind": family}},
        {"terms": {"status": [status.value for status in ACTIVE_STATUSES]}},
        {"terms": {"scope": [scope.value for scope in RELATABLE_SCOPES]}},
    ]
    try:
        if vector:
            search_ids |= _hit_ids(
                await opensearch.knn_search(
                    "memory",
                    vector,
                    project_id=str(item.project_id),
                    size=RELATION_CANDIDATES,
                    filters=filters,
                    include_org_memory=False,
                )
            )
        phrases = replacement_phrases(item.content)
        if phrases:
            search_ids |= _hit_ids(
                await opensearch.bm25_search(
                    "memory",
                    " ".join(phrases),
                    project_id=str(item.project_id),
                    size=RELATION_CANDIDATES,
                    filters=filters,
                    include_org_memory=False,
                )
            )
    except Exception as exc:
        logger.info("Memory index unavailable for relation candidates (%s): Postgres only", exc)

    pool = list(
        await session.scalars(
            select(MemoryItem)
            .where(*base)
            .order_by(MemoryItem.valid_from.desc())
            .limit(LEXICAL_CANDIDATE_POOL)
        )
    )
    by_id = {candidate.id: candidate for candidate in pool}

    def _lexical_score(candidate: MemoryItem) -> tuple[bool, float]:
        explicit = bool(
            replacement_phrase(item.content, candidate.content)
            or replacement_phrase(candidate.content, item.content)
        )
        return explicit, topic_similarity(item.content, candidate.content)

    scored = sorted(((c, _lexical_score(c)) for c in pool), key=lambda pair: pair[1], reverse=True)
    selected: dict[uuid.UUID, MemoryItem] = {
        c.id: c for c, (explicit, score) in scored[:RELATION_CANDIDATES] if explicit or score > 0
    }
    missing = search_ids - selected.keys()
    for candidate_id in list(missing):
        if candidate_id in by_id:
            selected[candidate_id] = by_id[candidate_id]
            missing.discard(candidate_id)
    if missing:
        for candidate in await session.scalars(select(MemoryItem).where(MemoryItem.id.in_(missing), *base)):
            selected[candidate.id] = candidate
    return list(selected.values())


async def _restored_pairs(session: AsyncSession, lineage_id: uuid.UUID) -> set[uuid.UUID]:
    """Lineages whose supersession with ``lineage_id`` was undone by a human (never auto-redone)."""
    events = await session.scalars(
        select(MemoryEvent).where(
            MemoryEvent.event == MemoryEventType.restored,
            or_(
                MemoryEvent.lineage_id == lineage_id,
                MemoryEvent.data["cleared_supersession_by"].astext == str(lineage_id),
                MemoryEvent.data["item_lineage_id"].astext == str(lineage_id),
            ),
        )
    )
    pairs: set[uuid.UUID] = set()
    for event in events:
        data = event.data or {}
        for key in ("cleared_supersession_by", "item_lineage_id"):
            value = data.get(key)
            if value:
                try:
                    pairs.add(uuid.UUID(str(value)))
                except ValueError:
                    continue
        if event.lineage_id != lineage_id:
            pairs.add(event.lineage_id)
    pairs.discard(lineage_id)
    return pairs


def _temporal_order(a: MemoryItem, b: MemoryItem) -> tuple[MemoryItem, MemoryItem] | None:
    """``(newer, older)`` when the two items have a clear temporal order, else ``None``."""
    if not a.valid_from or not b.valid_from or abs(a.valid_from - b.valid_from) < TEMPORAL_ORDER_MIN:
        return None
    return (a, b) if a.valid_from > b.valid_from else (b, a)


async def _flag_conflict(
    session: AsyncSession,
    a: MemoryItem,
    b: MemoryItem,
    similarity: float,
    markers: Sequence[str],
    actor: ActorLike,
) -> Relation | None:
    """Relation ``contradicts`` + ``conflict_detected`` events on both items (idempotent)."""
    if await _relation_between(session, a.id, b.id, RelationType.contradicts, both_ways=True):
        return None
    detail = f"Similarité {format_similarity(similarity)} · {join_markers(markers)}"
    relation = Relation(
        project_id=a.project_id,
        src_type=RelationNodeType.memory,
        src_id=a.id,
        rel_type=RelationType.contradicts,
        dst_type=RelationNodeType.memory,
        dst_id=b.id,
        confidence=round(_clamp(similarity), 3),
        detail=detail,
    )
    session.add(relation)
    for this, other in ((a, b), (b, a)):
        await record_event(
            session,
            this,
            MemoryEventType.conflict_detected,
            actor,
            reason=f"Contradiction détectée avec {_quote(other.title)} : {join_markers(markers)}",
            data={
                "with_id": other.id,
                "with_lineage_id": other.lineage_id,
                "with_title": other.title,
                "similarity": round(similarity, 3),
                "markers": list(markers),
            },
        )
    await audit.record(
        session,
        a.project_id,
        actor,
        AuditAction.memory_conflict,
        "memory",
        a.id,
        summary=f"Contradiction détectée entre {_quote(a.title)} et {_quote(b.title)}",
        details={"items": [a.id, b.id], "markers": list(markers), "similarity": round(similarity, 3)},
    )
    await session.flush()
    return relation


async def detect_relations(
    session: AsyncSession,
    item: MemoryItem,
    *,
    vector: Sequence[float] | None = None,
    actor: ActorLike = None,
) -> list[Relation]:
    """Supersession / contradiction detection against current active items of the project."""
    if (
        item.project_id is None
        or not item.is_current
        or MemoryScope(item.scope) not in RELATABLE_SCOPES
        or not is_active(item)
        or item.content == FORGOTTEN_CONTENT
    ):
        return []
    system = Actor.system() if actor is None else resolve_actor(actor)
    if vector is None:
        computed = await embed_texts([embedding_text(item)])
        vector = computed[0] if computed else None
    candidates = await _relation_candidates(session, item, vector)
    if not candidates:
        return []
    candidate_vectors = await embed_texts([embedding_text(c) for c in candidates]) if vector else None
    vectors: list[Sequence[float] | None] = (
        list(candidate_vectors) if candidate_vectors else [None] * len(candidates)
    )
    restored = await _restored_pairs(session, item.lineage_id)
    pairs = zip(candidates, vectors, strict=True)
    scored = sorted(
        ((c, relation_similarity(item.content, c.content, vector, v)) for c, v in pairs),
        key=lambda pair: pair[1],
        reverse=True,
    )

    created: list[Relation] = []
    for candidate, similarity in scored:
        if not is_active(item):
            break  # the item itself has just been superseded
        if not is_active(candidate):
            continue
        order = _temporal_order(item, candidate)
        both_decisions = MemoryKind(item.kind) == MemoryKind.decision and MemoryKind(candidate.kind) == (
            MemoryKind.decision
        )
        if both_decisions and order is not None and candidate.lineage_id not in restored:
            newer, older = order
            phrase = replacement_phrase(newer.content, older.content)
            if similarity > SUPERSEDE_SIMILARITY or (phrase and similarity >= REPLACEMENT_MIN_SIMILARITY):
                if await _relation_between(
                    session, newer.id, older.id, RelationType.supersedes, both_ways=True
                ):
                    continue
                basis = (
                    f"remplacement explicite (« {phrase} »)"
                    if phrase
                    else f"similarité {format_similarity(similarity)}"
                )
                confidence = max(similarity, EXPLICIT_REPLACEMENT_CONFIDENCE) if phrase else similarity
                if MemoryStatus(newer.status) == MemoryStatus.validated or MemoryStatus(older.status) == (
                    MemoryStatus.proposed
                ):
                    created.append(
                        await _apply_supersession(
                            session,
                            older,
                            newer,
                            system,
                            reason_old=(
                                f"Remplacé automatiquement par {_quote(newer.title)} : source plus récente "
                                f"({_date_label(newer.valid_from)}), {basis}"
                            ),
                            reason_new=f"Remplace {_quote(older.title)} ({basis})",
                            confidence=confidence,
                            detail=f"Source plus récente · {basis}",
                            auto=True,
                        )
                    )
                else:
                    relation = await _flag_conflict(
                        session,
                        newer,
                        older,
                        similarity,
                        [f"{basis} — proposition plus récente en attente de validation"],
                        system,
                    )
                    if relation is not None:
                        created.append(relation)
                continue
        if similarity > CONFLICT_SIMILARITY:
            markers = divergences(item.content, candidate.content)
            if markers:
                relation = await _flag_conflict(session, item, candidate, similarity, markers, system)
                if relation is not None:
                    created.append(relation)
    return created


# --- Deduplication helper (extractor, consolidation) ----------------------------------------------


def is_duplicate(
    a_text: str,
    b_text: str,
    a_vector: Sequence[float] | None,
    b_vector: Sequence[float] | None,
    threshold: float,
) -> tuple[bool, float]:
    """Near-duplicate test: similarity above ``threshold`` and no divergence marker."""
    dense = cosine_similarity(a_vector, b_vector) if a_vector and b_vector else 0.0
    similarity = max(dense, duplicate_similarity(a_text, b_text))
    return similarity > threshold and not divergences(a_text, b_text), similarity


# --- Document forgetting propagation --------------------------------------------------------------


async def propagate_document_forget(session: AsyncSession, document: Document, actor: ActorLike) -> int:
    """Forget or down-weight memory items derived from a forgotten document. Returns affected count.

    Items whose document sources are all forgotten are forgotten; the others keep their content but
    their confidence is multiplied by 0.6. Excerpts quoting the forgotten document are wiped.
    """
    resolved = resolve_actor(actor)
    chunk_ids = select(Chunk.id).where(Chunk.document_id == document.id)
    linked = or_(MemoryProvenance.document_id == document.id, MemoryProvenance.chunk_id.in_(chunk_ids))
    lineage_ids = list(
        await session.scalars(
            select(MemoryItem.lineage_id)
            .join(MemoryProvenance, MemoryProvenance.memory_item_id == MemoryItem.id)
            .where(linked)
            .distinct()
        )
    )
    if not lineage_ids:
        return 0
    # Wipe excerpts quoting the forgotten document (every version).
    await session.execute(
        update(MemoryProvenance)
        .where(linked)
        .values(excerpt=FORGOTTEN_CONTENT)
        .execution_options(synchronize_session=False)
    )
    items = list(
        await session.scalars(
            select(MemoryItem).where(
                MemoryItem.lineage_id.in_(lineage_ids),
                MemoryItem.is_current.is_(True),
                MemoryItem.status != MemoryStatus.forgotten,
            )
        )
    )
    affected = 0
    reduced: list[str] = []
    for item in items:
        source_document = func.coalesce(MemoryProvenance.document_id, Chunk.document_id)
        rows = await session.execute(
            select(source_document, Document.status)
            .select_from(MemoryProvenance)
            .outerjoin(Chunk, Chunk.id == MemoryProvenance.chunk_id)
            .outerjoin(Document, Document.id == source_document)
            .where(MemoryProvenance.memory_item_id == item.id)
        )
        statuses = {doc_id: status for doc_id, status in rows.tuples() if doc_id is not None}
        statuses[document.id] = DocumentStatus.forgotten
        all_forgotten = all(
            status is not None and DocumentStatus(status) == DocumentStatus.forgotten
            for status in statuses.values()
        )
        if all_forgotten:
            await forget(session, item, resolved, f"Source oubliée : {_quote(document.title)}")
        else:
            before = float(item.confidence)
            item.confidence = round(max(MIN_CONFIDENCE, before * FORGET_CONFIDENCE_FACTOR), 3)
            await record_event(
                session,
                item,
                MemoryEventType.edited,
                resolved,
                reason=f"Source oubliée : {_quote(document.title)} — confiance réduite",
                data={
                    "diff": {"confidence": {"from": round(before, 3), "to": item.confidence}},
                    "document_id": document.id,
                },
            )
            await _index_update([item.id], {"confidence": item.confidence})
            reduced.append(item.title)
        affected += 1
    if reduced:
        await audit.record(
            session,
            document.project_id,
            resolved,
            AuditAction.memory_edit,
            "document",
            document.id,
            summary=(
                f"Oubli de {_quote(document.title)} : confiance réduite pour {len(reduced)} item(s) mémoire"
            ),
            details={"items": reduced[:50]},
        )
    await session.flush()
    return affected


# --- Periodic maintenance -------------------------------------------------------------------------


async def _expire_short_term(session: AsyncSession, now: datetime) -> int:
    items = list(
        await session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.is_current.is_(True),
                MemoryItem.scope == MemoryScope.short_term,
                MemoryItem.status.in_(ACTIVE_STATUSES),
                MemoryItem.expires_at.is_not(None),
                MemoryItem.expires_at < now,
            )
            .limit(MAINTENANCE_BATCH)
        )
    )
    per_project: dict[uuid.UUID | None, int] = {}
    system = Actor.system()
    for item in items:
        previous = MemoryStatus(item.status)
        item.status = MemoryStatus.obsolete
        await record_event(
            session,
            item,
            MemoryEventType.obsoleted,
            system,
            reason="Mémoire court terme expirée",
            data={"previous_status": previous, "expires_at": item.expires_at, "valid_to_set": False},
        )
        per_project[item.project_id] = per_project.get(item.project_id, 0) + 1
    for project_id, count in per_project.items():
        await audit.record(
            session,
            project_id,
            system,
            AuditAction.memory_obsolete,
            "memory",
            None,
            summary=f"{count} item(s) de mémoire court terme expiré(s)",
            details={"count": count},
        )
    await session.flush()
    await _index_update([item.id for item in items], {"status": MemoryStatus.obsolete.value})
    return len(items)


async def _decay_long_term(session: AsyncSession, now: datetime) -> int:
    since = now - LONG_TERM_DECAY_AFTER
    reinforced = (
        select(MemoryItem.lineage_id)
        .join(ContextDecision, ContextDecision.memory_item_id == MemoryItem.id)
        .join(ContextRequest, ContextRequest.id == ContextDecision.request_id)
        .where(ContextDecision.included.is_(True), ContextRequest.created_at >= since)
    )
    items = list(
        await session.scalars(
            select(MemoryItem)
            .where(
                MemoryItem.is_current.is_(True),
                MemoryItem.scope == MemoryScope.long_term,
                MemoryItem.status == MemoryStatus.validated,
                MemoryItem.kind.in_(LONG_TERM_DECAY_KINDS),
                MemoryItem.updated_at < since,
                MemoryItem.confidence > LONG_TERM_MIN_CONFIDENCE,
                MemoryItem.lineage_id.not_in(reinforced),
            )
            .limit(MAINTENANCE_BATCH)
        )
    )
    for item in items:
        decayed = float(item.confidence) * LONG_TERM_DECAY_FACTOR
        item.confidence = round(max(LONG_TERM_MIN_CONFIDENCE, decayed), 3)
        item.updated_at = now
    await session.flush()
    for item in items:
        await _index_update([item.id], {"confidence": item.confidence})
    return len(items)


async def _trigger_consolidations(session: AsyncSession, now: datetime) -> int:
    from app.ingestion.queue import enqueue_job

    projects = list(await session.execute(select(Project.id, Project.settings)))
    pending = set(
        await session.scalars(
            select(IngestionJob.project_id).where(
                IngestionJob.kind == JobKind.consolidate,
                IngestionJob.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )
    )
    enqueued = 0
    for project_id, raw_settings in projects:
        if project_id in pending:
            continue
        ttl = int(project_service.normalize_settings(raw_settings)["short_term_ttl_hours"])
        threshold = now - short_term.idle_threshold(ttl)
        try:
            sessions = await short_term.list_sessions(project_id)
        except Exception as exc:
            logger.warning("Valkey unavailable during memory maintenance: %s", exc)
            return enqueued
        if any(info.updated_at < threshold for info in sessions):
            await enqueue_job(session, project_id, JobKind.consolidate, payload={"trigger": "maintenance"})
            enqueued += 1
    return enqueued


async def run_periodic_maintenance(session: AsyncSession) -> dict[str, int]:
    """Called by the worker every ``ORBIT_WORKER_MAINTENANCE_INTERVAL_SECONDS``: expire short-term
    items, confidence decay of long-term items, consolidation triggers. Returns counters (logged).
    Counters equal to zero are omitted (an empty dict means nothing to do)."""
    now = utcnow()
    counters = {
        "expired_short_term": await _expire_short_term(session, now),
        "decayed_long_term": await _decay_long_term(session, now),
        "consolidations_enqueued": await _trigger_consolidations(session, now),
    }
    return {key: value for key, value in counters.items() if value}
