"""Governed memory (docs/API.md « Mémoire », ARCHITECTURE §8). Business rules live in
``app.memory.lifecycle``; this router resolves visibility, permissions and serialization.

Visibility (``app.memory.visibility``): project items + organisation long-term items, classification
≤ clearance, ACL intersecting the caller's principals, user-scope items private to their subject.
Items the caller cannot see answer ``404`` (their existence is not revealed).

Route order matters: ``/memory/graph`` and ``/memory/consolidate`` are declared before
``/memory/{memory_id}``.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import AgentEditorAccess, EditorAccess, ProjectAccess, SessionDep, ViewerAccess
from app.enums import (
    DocumentStatus,
    JobKind,
    JobStatus,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RelationNodeType,
    RelationType,
    Role,
)
from app.errors import forbidden, not_found, validation_error
from app.governance.acl import acl_allows
from app.ingestion.pipeline import actor_payload
from app.ingestion.queue import enqueue_job
from app.memory import entities as entity_service
from app.memory import lifecycle
from app.memory.serializers import serialize_events, serialize_item, serialize_items
from app.memory.visibility import MemoryViewer, can_view, visibility_clause
from app.models import Chunk, Document, IngestionJob, MemoryEvent, MemoryProvenance, Relation, Source
from app.models import MemoryItem as MemoryItemRow
from app.schemas import (
    Job,
    MemoryDetail,
    MemoryGraph,
    MemoryIn,
    MemoryItem,
    MemoryUpdateIn,
    Page,
    PageParams,
    ReasonIn,
    ReasonRequiredIn,
    SupersedeIn,
    page_params,
)
from app.schemas.common import make_page
from app.schemas.memory import GraphEdge, GraphNode, Provenance
from app.schemas.memory import Relation as RelationOut
from app.services import projects as project_service

router = APIRouter(prefix="/projects/{slug}/memory", tags=["memory"])

ITEM_NOT_FOUND = "Item mémoire introuvable"
RESTRICTED_DOCUMENT_TITLE = "Document restreint"
HISTORY_LIMIT = 200
RELATIONS_LIMIT = 200


# --- Helpers -------------------------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _document_visible(document: Document, viewer: MemoryViewer) -> bool:
    return (
        document.project_id == viewer.project_id
        and int(document.classification) <= viewer.clearance
        and acl_allows(document.acl_principals, viewer.principals)
    )


async def _visible_item(session: AsyncSession, access: ProjectAccess, memory_id: uuid.UUID) -> MemoryItemRow:
    """Item (any version, or current version of a lineage id) visible to the caller, else 404."""
    item = await lifecycle.get_item(session, memory_id)
    if item is None or not can_view(item, MemoryViewer.from_access(access)):
        raise not_found(ITEM_NOT_FOUND)
    return item


async def _mutable_item(session: AsyncSession, access: ProjectAccess, memory_id: uuid.UUID) -> MemoryItemRow:
    """Current version of a visible item the caller may change."""
    item = await lifecycle.ensure_current(session, await _visible_item(session, access, memory_id))
    if item.project_id is None and not access.is_admin:
        raise forbidden("La mémoire d'organisation n'est modifiable que par un administrateur")
    return item


def _check_classification(level: int | None, access: ProjectAccess) -> None:
    if level is not None and int(level) > int(access.principal.clearance):
        raise forbidden("Niveau de classification supérieur à votre habilitation")


async def _check_provenance(session: AsyncSession, body: MemoryIn, viewer: MemoryViewer) -> None:
    """The caller may only derive memory from sources they can read."""
    for entry in body.provenance or []:
        document_id = entry.document_id
        if entry.chunk_id is not None:
            chunk = await session.get(Chunk, entry.chunk_id)
            if chunk is None or chunk.project_id != viewer.project_id:
                raise validation_error("Fragment de source introuvable dans ce projet")
            if int(chunk.classification) > viewer.clearance or not acl_allows(
                chunk.acl_principals, viewer.principals
            ):
                raise not_found("Fragment de source introuvable dans ce projet")
            document_id = document_id or chunk.document_id
        if document_id is not None:
            document = await session.get(Document, document_id)
            if document is None or not _document_visible(document, viewer):
                raise validation_error("Document source introuvable dans ce projet")


async def _rows_by_id[T: (Document, Chunk, MemoryItemRow)](
    session: AsyncSession, model: type[T], ids: set[uuid.UUID]
) -> dict[uuid.UUID, T]:
    if not ids:
        return {}
    rows = await session.scalars(select(model).where(model.id.in_(ids)))
    return {row.id: row for row in rows}


async def _commit_and_serialize(session: AsyncSession, item: MemoryItemRow) -> MemoryItem:
    await session.commit()
    return await serialize_item(session, item)


# --- Listing & creation -------------------------------------------------------------------------------


def _as_of_conditions(as_of: datetime, project_id: uuid.UUID) -> list[Any]:
    """§D2 « tel que connu au <date> »: latest version of each lineage created by ``as_of`` whose
    validity window covers it (forgotten items excluded)."""
    ranked = (
        select(
            MemoryItemRow.id.label("id"),
            func.row_number()
            .over(partition_by=MemoryItemRow.lineage_id, order_by=MemoryItemRow.version.desc())
            .label("rank"),
        )
        .where(
            MemoryItemRow.created_at <= as_of,
            or_(MemoryItemRow.project_id == project_id, MemoryItemRow.project_id.is_(None)),
        )
        .subquery()
    )
    known = select(ranked.c.id).where(ranked.c.rank == 1)
    return [
        MemoryItemRow.id.in_(known),
        MemoryItemRow.valid_from <= as_of,
        or_(MemoryItemRow.valid_to.is_(None), MemoryItemRow.valid_to > as_of),
        MemoryItemRow.status != MemoryStatus.forgotten,
    ]


@router.get(
    "", response_model=Page[MemoryItem], summary="Items mémoire (versions courantes, filtrés par droits)"
)
async def list_memory(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    scope: MemoryScope | None = Query(default=None),
    kind: MemoryKind | None = Query(default=None),
    status_: MemoryStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    include_history: bool = Query(default=False),
    as_of: datetime | None = Query(default=None, description="Mémoire telle que connue à cette date (§D2)"),
) -> Page[MemoryItem]:
    viewer = MemoryViewer.from_access(access)
    conditions = [visibility_clause(viewer)]
    if as_of is not None:
        when = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
        conditions.extend(_as_of_conditions(when, viewer.project_id))
    elif not include_history:
        conditions.append(MemoryItemRow.is_current.is_(True))
    if scope is not None:
        conditions.append(MemoryItemRow.scope == scope)
    if kind is not None:
        conditions.append(MemoryItemRow.kind == kind)
    if status_ is not None:
        conditions.append(MemoryItemRow.status == status_)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        conditions.append(
            or_(
                MemoryItemRow.title.ilike(pattern, escape="\\"),
                MemoryItemRow.content.ilike(pattern, escape="\\"),
            )
        )
    total = await session.scalar(select(func.count()).select_from(MemoryItemRow).where(*conditions))
    rows = await session.scalars(
        select(MemoryItemRow)
        .where(*conditions)
        .order_by(MemoryItemRow.updated_at.desc(), MemoryItemRow.version.desc(), MemoryItemRow.id)
        .offset(params.offset)
        .limit(params.limit)
    )
    items = await serialize_items(session, list(rows))
    return make_page(items, int(total or 0), params)


@router.post(
    "", response_model=MemoryItem, status_code=status.HTTP_201_CREATED, summary="Créer un item mémoire"
)
async def create_memory(body: MemoryIn, access: AgentEditorAccess, session: SessionDep) -> MemoryItem:
    principal = access.principal
    viewer = MemoryViewer.from_access(access)
    _check_classification(body.classification, access)
    await _check_provenance(session, body, viewer)

    scope = MemoryScope(body.scope)
    if scope == MemoryScope.user:
        subject = body.subject_user_id or principal.user_id
        if subject is None:
            raise validation_error("« subject_user_id » est requis pour la mémoire utilisateur")
        if principal.is_user and subject != principal.user_id:
            raise forbidden("La mémoire utilisateur ne peut être enregistrée que pour soi-même")
        if (
            principal.is_agent
            and await project_service.get_member_role(session, access.project_id, subject) is None
        ):
            raise validation_error("L'utilisateur concerné n'est pas membre du projet")
        body = body.model_copy(update={"subject_user_id": subject})

    project_id: uuid.UUID | None = access.project_id
    if (
        scope == MemoryScope.long_term
        and principal.is_admin
        and lifecycle.ORG_MEMORY_TAG in (body.tags or [])
        and not body.provenance
    ):
        project_id = None  # organisation-wide long-term memory

    item = await lifecycle.create_item(
        session,
        project_id=project_id,
        data=body,
        actor=principal.actor,
        force_status=MemoryStatus.proposed.value if principal.is_agent else None,
    )
    await session.commit()
    return await serialize_item(session, item)


@router.post("/consolidate", response_model=Job, summary="Lancer une consolidation mémoire")
async def consolidate_memory(access: EditorAccess, session: SessionDep) -> Job:
    pending = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.project_id == access.project_id,
            IngestionJob.kind == JobKind.consolidate,
            IngestionJob.status.in_([JobStatus.queued, JobStatus.running]),
        )
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    if pending is not None:
        return Job.model_validate(pending)
    job = await enqueue_job(
        session,
        access.project_id,
        JobKind.consolidate,
        payload={"trigger": "manual", "actor": actor_payload(access.principal.actor)},
    )
    await session.commit()
    await session.refresh(job)
    return Job.model_validate(job)


# --- Graph --------------------------------------------------------------------------------------------


@router.get("/graph", response_model=MemoryGraph, summary="Graphe mémoire")
async def memory_graph(
    access: ViewerAccess, session: SessionDep, limit: int = Query(default=150, ge=1, le=1000)
) -> MemoryGraph:
    viewer = MemoryViewer.from_access(access)
    items = list(
        await session.scalars(
            select(MemoryItemRow)
            .where(
                visibility_clause(viewer),
                MemoryItemRow.is_current.is_(True),
                MemoryItemRow.status != MemoryStatus.forgotten,
            )
            .order_by(MemoryItemRow.updated_at.desc())
            .limit(limit)
        )
    )
    item_ids = {item.id for item in items}
    nodes: list[GraphNode] = [
        GraphNode(
            id=str(item.id),
            type=RelationNodeType.memory.value,
            label=item.title,
            kind=MemoryKind(item.kind).value,
            status=MemoryStatus(item.status).value,
        )
        for item in items
    ]
    edges: list[GraphEdge] = []
    if not item_ids:
        return MemoryGraph(nodes=nodes, edges=edges)

    relations = list(
        await session.scalars(
            select(Relation).where(
                or_(
                    (Relation.src_type == RelationNodeType.memory) & Relation.src_id.in_(item_ids),
                    (Relation.dst_type == RelationNodeType.memory) & Relation.dst_id.in_(item_ids),
                )
            )
        )
    )
    document_ids = {
        r.dst_id
        for r in relations
        if r.src_id in item_ids
        and r.dst_type == RelationNodeType.document
        and r.rel_type == RelationType.derived_from
    }
    documents: dict[uuid.UUID, tuple[Document, str]] = {}
    budget = max(0, limit - len(nodes))
    if document_ids and budget:
        rows = await session.execute(
            select(Document, Source.kind)
            .join(Source, Source.id == Document.source_id)
            .where(Document.id.in_(document_ids), Document.status != DocumentStatus.forgotten)
            .order_by(Document.updated_at.desc())
        )
        for document, source_kind in rows.tuples():
            if len(documents) >= budget:
                break
            if _document_visible(document, viewer):
                documents[document.id] = (document, str(source_kind))
    for graph_document, graph_kind in documents.values():
        nodes.append(
            GraphNode(
                id=str(graph_document.id),
                type=RelationNodeType.document.value,
                label=graph_document.title,
                kind=graph_kind,
                status=DocumentStatus(graph_document.status).value,
            )
        )
    node_ids = item_ids | set(documents)
    seen: set[tuple[uuid.UUID, uuid.UUID, RelationType]] = set()
    for relation in relations:
        key = (relation.src_id, relation.dst_id, RelationType(relation.rel_type))
        if relation.src_id not in node_ids or relation.dst_id not in node_ids or key in seen:
            continue
        seen.add(key)
        edges.append(
            GraphEdge(
                source=str(relation.src_id),
                target=str(relation.dst_id),
                rel_type=relation.rel_type,
                confidence=float(relation.confidence),
                detail=relation.detail,
                method=relation.method,
            )
        )
    await _entity_layer(session, access.project_id, items, nodes, edges, max(0, limit - len(nodes)))
    return MemoryGraph(nodes=nodes, edges=edges)


async def _entity_layer(
    session: AsyncSession,
    project_id: uuid.UUID,
    items: list[MemoryItemRow],
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    budget: int,
) -> None:
    """§D2 richer graph: entity nodes linked (``mentions``) to the visible items naming one of their
    aliases. Only entity names are added — never content the viewer cannot see."""
    if not items or budget <= 0:
        return
    active = await entity_service.active_entities(session, project_id)
    if not active:
        return
    aliases = await entity_service.aliases_of(session, [e.id for e in active])
    texts = [(item, entity_service.normalize(f"{item.title} {item.content}")) for item in items]
    for entity in active:
        if budget <= 0:
            break
        forms = [a.normalized for a in aliases.get(entity.id, []) if a.normalized] or [
            entity_service.normalize(entity.name)
        ]
        patterns = [re.compile(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])") for f in forms]
        linked = [item for item, text in texts if any(p.search(text) for p in patterns)]
        if not linked:
            continue
        budget -= 1
        nodes.append(GraphNode(id=str(entity.id), type="entity", label=entity.name, kind=entity.kind))
        edges.extend(
            GraphEdge(source=str(item.id), target=str(entity.id), rel_type=RelationType.mentions)
            for item in linked
        )


# --- Detail -------------------------------------------------------------------------------------------


async def _provenance(session: AsyncSession, item: MemoryItemRow, viewer: MemoryViewer) -> list[Provenance]:
    rows = list(
        await session.scalars(
            select(MemoryProvenance)
            .where(MemoryProvenance.memory_item_id == item.id)
            .order_by(MemoryProvenance.created_at)
        )
    )
    document_ids = {row.document_id for row in rows if row.document_id}
    documents = await _rows_by_id(session, Document, document_ids)
    result: list[Provenance] = []
    for row in rows:
        out = Provenance.model_validate(row)
        document = documents.get(row.document_id) if row.document_id else None
        if document is not None:
            if _document_visible(document, viewer):
                out.document_title = document.title
            else:
                out.document_title = RESTRICTED_DOCUMENT_TITLE
                out.excerpt = ""
                out.source_label = RESTRICTED_DOCUMENT_TITLE
        result.append(out)
    return result


async def _relations(
    session: AsyncSession, item: MemoryItemRow, version_ids: set[uuid.UUID], viewer: MemoryViewer
) -> list[RelationOut]:
    rows = list(
        await session.scalars(
            select(Relation)
            .where(
                or_(
                    (Relation.src_type == RelationNodeType.memory) & Relation.src_id.in_(version_ids),
                    (Relation.dst_type == RelationNodeType.memory) & Relation.dst_id.in_(version_ids),
                )
            )
            .order_by(Relation.created_at.desc())
            .limit(RELATIONS_LIMIT)
        )
    )
    others: list[tuple[Relation, Literal["out", "in"], RelationNodeType, uuid.UUID]] = []
    for relation in rows:
        if relation.src_type == RelationNodeType.memory and relation.src_id in version_ids:
            if relation.dst_type == RelationNodeType.memory and relation.dst_id in version_ids:
                continue  # relation inside the lineage
            others.append((relation, "out", RelationNodeType(relation.dst_type), relation.dst_id))
        else:
            others.append((relation, "in", RelationNodeType(relation.src_type), relation.src_id))

    memory_ids = {oid for _, _, otype, oid in others if otype == RelationNodeType.memory}
    chunk_ids = {oid for _, _, otype, oid in others if otype == RelationNodeType.chunk}
    memories = await _rows_by_id(session, MemoryItemRow, memory_ids)
    chunks = await _rows_by_id(session, Chunk, chunk_ids)
    document_ids = {oid for _, _, otype, oid in others if otype == RelationNodeType.document}
    document_ids |= {c.document_id for c in chunks.values()}
    documents = await _rows_by_id(session, Document, document_ids)

    result: list[RelationOut] = []
    seen: set[tuple[RelationType, Literal["out", "in"], uuid.UUID]] = set()
    for relation, direction, other_type, other_id in others:
        title: str | None = None
        if other_type == RelationNodeType.memory:
            other = memories.get(other_id)
            if other is None or not can_view(other, viewer):
                continue
            if not other.is_current:
                other = await lifecycle.ensure_current(session, other)
                other_id = other.id
            title = other.title
        elif other_type == RelationNodeType.document:
            document = documents.get(other_id)
            if document is None or not _document_visible(document, viewer):
                continue
            title = document.title
        else:
            chunk = chunks.get(other_id)
            document = documents.get(chunk.document_id) if chunk else None
            if chunk is None or document is None or not _document_visible(document, viewer):
                continue
            title = f"{document.title} · §{chunk.ordinal + 1}"
        key = (RelationType(relation.rel_type), direction, other_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            RelationOut(
                id=relation.id,
                rel_type=relation.rel_type,
                direction=direction,
                other_type=other_type,
                other_id=other_id,
                other_title=title,
                confidence=float(relation.confidence),
                detail=relation.detail,
                method=relation.method,
                score=relation.score,
                explanation=relation.explanation,
                created_at=relation.created_at,
            )
        )
    return result


@router.get("/{memory_id}", response_model=MemoryDetail, summary="Détail d'un item mémoire")
async def get_memory(memory_id: uuid.UUID, access: ViewerAccess, session: SessionDep) -> MemoryDetail:
    viewer = MemoryViewer.from_access(access)
    item = await _visible_item(session, access, memory_id)
    versions = [v for v in await lifecycle.lineage_versions(session, item.lineage_id) if can_view(v, viewer)]
    events = list(
        await session.scalars(
            select(MemoryEvent)
            .where(MemoryEvent.lineage_id == item.lineage_id)
            .order_by(MemoryEvent.created_at.desc(), MemoryEvent.id)
            .limit(HISTORY_LIMIT)
        )
    )
    version_ids = {v.id for v in versions} | {item.id}
    return MemoryDetail(
        item=await serialize_item(session, item),
        provenance=await _provenance(session, item, viewer),
        history=await serialize_events(session, events),
        versions=await serialize_items(session, versions),
        relations=await _relations(session, item, version_ids, viewer),
    )


# --- Mutations ----------------------------------------------------------------------------------------


@router.patch("/{memory_id}", response_model=MemoryItem, summary="Modifier (crée une nouvelle version)")
async def update_memory(
    memory_id: uuid.UUID, body: MemoryUpdateIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    item = await _mutable_item(session, access, memory_id)
    _check_classification(body.classification, access)
    if not body.model_dump(exclude_unset=True):
        raise validation_error("Aucune modification fournie")
    updated = await lifecycle.new_version(session, item, body, access.principal.actor)
    return await _commit_and_serialize(session, updated)


@router.post("/{memory_id}/validate", response_model=MemoryItem, summary="Valider")
async def validate_memory(
    memory_id: uuid.UUID, body: ReasonIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    item = await _mutable_item(session, access, memory_id)
    updated = await lifecycle.validate(session, item, access.principal.actor, body.reason)
    return await _commit_and_serialize(session, updated)


@router.post("/{memory_id}/obsolete", response_model=MemoryItem, summary="Marquer obsolète")
async def obsolete_memory(
    memory_id: uuid.UUID, body: ReasonRequiredIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    item = await _mutable_item(session, access, memory_id)
    updated = await lifecycle.obsolete(session, item, access.principal.actor, body.reason)
    return await _commit_and_serialize(session, updated)


@router.post("/{memory_id}/supersede", response_model=MemoryItem, summary="Remplacer par un autre item")
async def supersede_memory(
    memory_id: uuid.UUID, body: SupersedeIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    item = await _mutable_item(session, access, memory_id)
    replacement = await lifecycle.ensure_current(session, await _visible_item(session, access, body.by_id))
    updated = await lifecycle.supersede(session, item, replacement, access.principal.actor, body.reason)
    return await _commit_and_serialize(session, updated)


@router.post("/{memory_id}/restore", response_model=MemoryItem, summary="Restaurer")
async def restore_memory(
    memory_id: uuid.UUID, body: ReasonIn, access: EditorAccess, session: SessionDep
) -> MemoryItem:
    item = await _mutable_item(session, access, memory_id)
    updated = await lifecycle.restore(session, item, access.principal.actor, body.reason)
    return await _commit_and_serialize(session, updated)


@router.post(
    "/{memory_id}/forget",
    response_model=MemoryItem,
    summary="Oubli sélectif (owner, ou sujet pour la portée user)",
)
async def forget_memory(
    memory_id: uuid.UUID, body: ReasonRequiredIn, access: ViewerAccess, session: SessionDep
) -> MemoryItem:
    """Access check inside: owner, or the subject user for ``scope=user`` items."""
    item = await lifecycle.ensure_current(session, await _visible_item(session, access, memory_id))
    is_subject = (
        MemoryScope(item.scope) == MemoryScope.user
        and access.principal.user_id is not None
        and item.subject_user_id == access.principal.user_id
    )
    if not is_subject:
        if item.project_id is None and not access.is_admin:
            raise forbidden("La mémoire d'organisation ne peut être oubliée que par un administrateur")
        access.require(Role.owner)
    updated = await lifecycle.forget(session, item, access.principal.actor, body.reason)
    return await _commit_and_serialize(session, updated)


__all__ = ["router"]
