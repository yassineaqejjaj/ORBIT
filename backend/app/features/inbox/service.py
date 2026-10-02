"""Memory triage (proposals) and conflict arbitration — docs/FEATURES.md F1.

Business rules stay in ``app.memory.lifecycle`` (validate / obsolete / supersede); this module adds
the triage signals (impact, would-be inclusions, probable duplicates), bulk actions and the
arbitration records of ``contradicts`` relations.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import ScalarSelect

from app.db import utcnow
from app.enums import MemoryKind, MemoryStatus, ReasonCode, RelationType
from app.errors import ApiError, conflict, forbidden, not_found, validation_error
from app.features.inbox.schemas import (
    BulkFailure,
    BulkIn,
    BulkOut,
    Conflict,
    ConflictResolutionOut,
    ConflictSide,
    InboxItem,
    SimilarItem,
)
from app.governance.acl import acl_allows
from app.memory import lifecycle
from app.memory.conflicts import conflict_winner, divergences, duplicate_similarity, kind_family
from app.memory.serializers import serialize_items
from app.memory.visibility import MemoryViewer, can_view, visibility_clause
from app.models import ContextDecision, ContextRequest, Document, MemoryItem, MemoryProvenance, Relation
from app.models.features_feed import ConflictResolution
from app.schemas.memory import Provenance
from app.services import audit

if TYPE_CHECKING:
    from app.deps import ProjectAccess

ITEM_NOT_FOUND = "Item mémoire introuvable"
CONFLICT_NOT_FOUND = "Contradiction introuvable"
RESTRICTED_DOCUMENT_TITLE = "Document restreint"
REJECT_REASON = "Rejeté au tri"
IMPACT_WINDOW = timedelta(days=30)
#: Exclusions a validation would likely have avoided (proposed items are ranked lower, ARCHITECTURE §9).
VALIDATION_SENSITIVE = (
    ReasonCode.EXCLUDED_LOW_SCORE,
    ReasonCode.EXCLUDED_BUDGET,
    ReasonCode.EXCLUDED_CONFLICT,
)
SIMILAR_THRESHOLD = 0.6
SIMILAR_POOL = 500
STATUS_LABELS = {MemoryStatus.validated: "validé", MemoryStatus.proposed: "proposé"}

Sort = Literal["impact", "confidence", "recent"]


def _quote(title: str) -> str:
    title = " ".join((title or "").split())
    return f"« {title[:89] + '…' if len(title) > 90 else title} »"


# --- Proposals ------------------------------------------------------------------------------------------


def _impact_subqueries() -> tuple[ScalarSelect[int], ScalarSelect[int]]:
    """Correlated counts: distinct contexts (30 days) where the item was a candidate / was excluded."""
    since = utcnow() - IMPACT_WINDOW
    base = (
        select(func.count(func.distinct(ContextDecision.request_id)))
        .join(ContextRequest, ContextRequest.id == ContextDecision.request_id)
        .where(ContextDecision.memory_item_id == MemoryItem.id, ContextRequest.created_at >= since)
    )
    impact = base.correlate(MemoryItem).scalar_subquery()
    would = (
        base.where(ContextDecision.included.is_(False), ContextDecision.reason_code.in_(VALIDATION_SENSITIVE))
        .correlate(MemoryItem)
        .scalar_subquery()
    )
    return impact, would


def _proposal_conditions(
    viewer: MemoryViewer, kind: MemoryKind | None, min_confidence: float | None
) -> list[object]:
    conditions: list[object] = [
        visibility_clause(viewer),
        MemoryItem.project_id == viewer.project_id,
        MemoryItem.is_current.is_(True),
        MemoryItem.status == MemoryStatus.proposed,
    ]
    if kind is not None:
        conditions.append(MemoryItem.kind == kind)
    if min_confidence is not None:
        conditions.append(MemoryItem.confidence >= min_confidence)
    return conditions


async def count_proposals(session: AsyncSession, viewer: MemoryViewer) -> int:
    conditions = _proposal_conditions(viewer, None, None)
    return int(await session.scalar(select(func.count()).select_from(MemoryItem).where(*conditions)) or 0)


async def list_proposals(
    session: AsyncSession,
    viewer: MemoryViewer,
    *,
    kind: MemoryKind | None,
    min_confidence: float | None,
    sort: Sort,
    offset: int,
    limit: int,
) -> tuple[list[InboxItem], int]:
    conditions = _proposal_conditions(viewer, kind, min_confidence)
    total = int(await session.scalar(select(func.count()).select_from(MemoryItem).where(*conditions)) or 0)
    impact, would = _impact_subqueries()
    order = {
        "impact": (impact.desc(), would.desc(), MemoryItem.confidence.desc()),
        "confidence": (MemoryItem.confidence.desc(), impact.desc()),
        "recent": (MemoryItem.created_at.desc(),),
    }[sort]
    rows = (
        await session.execute(
            select(MemoryItem, impact.label("impact"), would.label("would"))
            .where(*conditions)
            .order_by(*order, MemoryItem.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [row[0] for row in rows]
    serialized = await serialize_items(session, items)
    similar = await _similar(session, viewer, items)
    result: list[InboxItem] = []
    for (item, impact_value, would_value), out in zip(rows, serialized, strict=True):
        entry = InboxItem(**out.model_dump())
        entry.impact = int(impact_value or 0)
        entry.would_be_included = int(would_value or 0)
        entry.similar = similar.get(item.id)
        result.append(entry)
    return result, total


async def _similar(
    session: AsyncSession, viewer: MemoryViewer, items: Sequence[MemoryItem]
) -> dict[uuid.UUID, SimilarItem]:
    """Most similar other active item (probable duplicate) of each proposal."""
    if not items:
        return {}
    pool = list(
        await session.scalars(
            select(MemoryItem)
            .where(
                visibility_clause(viewer),
                MemoryItem.project_id == viewer.project_id,
                MemoryItem.is_current.is_(True),
                MemoryItem.status.in_((MemoryStatus.proposed, MemoryStatus.validated)),
            )
            .order_by(MemoryItem.updated_at.desc())
            .limit(SIMILAR_POOL)
        )
    )
    result: dict[uuid.UUID, SimilarItem] = {}
    for item in items:
        family = kind_family(item.kind)
        best: tuple[float, MemoryItem] | None = None
        for other in pool:
            if other.lineage_id == item.lineage_id or MemoryKind(other.kind) not in family:
                continue
            score = duplicate_similarity(item.content, other.content)
            if score >= SIMILAR_THRESHOLD and (best is None or score > best[0]):
                if divergences(item.content, other.content):
                    continue
                best = (score, other)
        if best is not None:
            result[item.id] = SimilarItem(id=best[1].id, title=best[1].title, score=round(best[0], 3))
    return result


# --- Bulk actions -----------------------------------------------------------------------------------------


async def _mutable(session: AsyncSession, access: ProjectAccess, item_id: uuid.UUID) -> MemoryItem:
    item = await lifecycle.get_item(session, item_id)
    if item is None or not can_view(item, MemoryViewer.from_access(access)):
        raise not_found(ITEM_NOT_FOUND)
    item = await lifecycle.ensure_current(session, item)
    if item.project_id is None and not access.is_admin:
        raise forbidden("La mémoire d'organisation n'est modifiable que par un administrateur")
    return item


async def _copy_provenance(session: AsyncSession, source: MemoryItem, target: MemoryItem) -> int:
    existing = list(
        await session.scalars(select(MemoryProvenance).where(MemoryProvenance.memory_item_id == target.id))
    )
    keys = {(p.document_id, p.chunk_id, p.context_request_id, p.excerpt) for p in existing}
    copied = 0
    for row in await session.scalars(
        select(MemoryProvenance).where(MemoryProvenance.memory_item_id == source.id)
    ):
        key = (row.document_id, row.chunk_id, row.context_request_id, row.excerpt)
        if key in keys:
            continue
        keys.add(key)
        session.add(
            MemoryProvenance(
                memory_item_id=target.id,
                document_id=row.document_id,
                chunk_id=row.chunk_id,
                context_request_id=row.context_request_id,
                source_label=row.source_label or f"Fusionné depuis {_quote(source.title)}",
                excerpt=row.excerpt,
            )
        )
        copied += 1
    return copied


async def bulk(session: AsyncSession, access: ProjectAccess, body: BulkIn) -> BulkOut:
    actor = access.principal.actor
    into: MemoryItem | None = None
    if body.action == "merge":
        assert body.into_id is not None
        into = await _mutable(session, access, body.into_id)
        if not lifecycle.is_active(into):
            raise conflict("L'item cible de la fusion doit être proposé ou validé")
    processed = 0
    failed: list[BulkFailure] = []
    copied = 0
    seen: set[uuid.UUID] = set()
    for item_id in body.ids:
        if item_id in seen:
            continue
        seen.add(item_id)
        if into is not None and item_id in (into.id, into.lineage_id):
            continue
        try:
            async with session.begin_nested():
                item = await _mutable(session, access, item_id)
                if body.action == "validate":
                    await lifecycle.validate(session, item, actor, body.reason)
                elif body.action == "reject":
                    reason = REJECT_REASON + (f" : {body.reason}" if body.reason else "")
                    await lifecycle.obsolete(session, item, actor, reason)
                else:
                    assert into is not None
                    if item.lineage_id == into.lineage_id:
                        raise validation_error("Un item ne peut pas être fusionné dans lui-même")
                    if item.project_id != into.project_id:
                        raise validation_error("Les deux items doivent appartenir au même projet")
                    copied += await _copy_provenance(session, item, into)
                    reason = f"Fusionné dans {_quote(into.title)}" + (
                        f" : {body.reason}" if body.reason else ""
                    )
                    await lifecycle.obsolete(session, item, actor, reason)
            processed += 1
        except ApiError as exc:
            failed.append(BulkFailure(id=item_id, detail=str(exc.detail)))
    labels = {"validate": "Validation", "reject": "Rejet", "merge": "Fusion"}
    await audit.record(
        session,
        access.project_id,
        actor,
        audit.AuditAction.memory_bulk,
        "memory",
        into.id if into is not None else None,
        summary=(
            f"{labels[body.action]} groupée au tri : {processed} item(s) traité(s), {len(failed)} échec(s)"
        ),
        details={
            "action": body.action,
            "ids": [str(i) for i in body.ids],
            "into_id": str(into.id) if into is not None else None,
            "processed": processed,
            "failed": [f.id for f in failed],
            "provenance_copied": copied,
            "reason": body.reason,
        },
    )
    await session.commit()
    return BulkOut(processed=processed, failed=failed)


# --- Conflicts ---------------------------------------------------------------------------------------------


def rationale(winner: MemoryItem, loser: MemoryItem) -> str:
    """French explanation of the suggested winner: validated > proposed, more recent, more reliable."""
    reasons: list[str] = []
    ws, ls = MemoryStatus(winner.status), MemoryStatus(loser.status)
    if ws != ls:
        reasons.append(f"{STATUS_LABELS.get(ws, ws.value)} (l'autre est {STATUS_LABELS.get(ls, ls.value)})")
    if winner.valid_from and loser.valid_from and winner.valid_from > loser.valid_from:
        reasons.append(f"plus récent ({winner.valid_from:%d/%m/%Y} contre {loser.valid_from:%d/%m/%Y})")
    if float(winner.confidence) > float(loser.confidence):
        reasons.append(f"plus fiable (confiance {winner.confidence:.0%} contre {loser.confidence:.0%})")
    if not reasons:
        return "Les deux items sont équivalents : choix par défaut, à confirmer"
    return "Suggéré car " + ", ".join(reasons)


def _document_visible(document: Document, viewer: MemoryViewer) -> bool:
    return (
        document.project_id == viewer.project_id
        and int(document.classification) <= viewer.clearance
        and acl_allows(document.acl_principals, viewer.principals)
    )


async def _sides(
    session: AsyncSession, viewer: MemoryViewer, items: Sequence[MemoryItem]
) -> dict[uuid.UUID, ConflictSide]:
    serialized = await serialize_items(session, items)
    rows = list(
        await session.scalars(
            select(MemoryProvenance)
            .where(MemoryProvenance.memory_item_id.in_([i.id for i in items]))
            .order_by(MemoryProvenance.created_at)
        )
    )
    doc_ids = {r.document_id for r in rows if r.document_id}
    documents = (
        {d.id: d for d in await session.scalars(select(Document).where(Document.id.in_(doc_ids)))}
        if doc_ids
        else {}
    )
    sources: dict[uuid.UUID, list[Provenance]] = {}
    for row in rows:
        out = Provenance.model_validate(row)
        document = documents.get(row.document_id) if row.document_id else None
        if document is not None:
            if _document_visible(document, viewer):
                out.document_title = document.title
            else:
                out.document_title = out.source_label = RESTRICTED_DOCUMENT_TITLE
                out.excerpt = ""
        sources.setdefault(row.memory_item_id, []).append(out)
    return {
        item.id: ConflictSide(**out.model_dump(), sources=sources.get(item.id, []))
        for item, out in zip(items, serialized, strict=True)
    }


async def _items(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, MemoryItem]:
    if not ids:
        return {}
    return {i.id: i for i in await session.scalars(select(MemoryItem).where(MemoryItem.id.in_(ids)))}


async def open_relations(
    session: AsyncSession, viewer: MemoryViewer
) -> list[tuple[Relation, MemoryItem, MemoryItem]]:
    relations = list(
        await session.scalars(
            select(Relation)
            .where(Relation.project_id == viewer.project_id, Relation.rel_type == RelationType.contradicts)
            .order_by(Relation.created_at.desc())
        )
    )
    items = await _items(session, {r.src_id for r in relations} | {r.dst_id for r in relations})
    result = []
    for relation in relations:
        a, b = items.get(relation.src_id), items.get(relation.dst_id)
        if a is None or b is None or not (can_view(a, viewer) and can_view(b, viewer)):
            continue
        if not (a.is_current and b.is_current and lifecycle.is_active(a) and lifecycle.is_active(b)):
            continue
        result.append((relation, a, b))
    return result


async def count_open_conflicts(session: AsyncSession, viewer: MemoryViewer) -> int:
    return len(await open_relations(session, viewer))


async def list_conflicts(
    session: AsyncSession, viewer: MemoryViewer, status: Literal["open", "resolved"]
) -> list[Conflict]:
    if status == "open":
        triples = await open_relations(session, viewer)
        sides = await _sides(session, viewer, [x for _, a, b in triples for x in (a, b)])
        out: list[Conflict] = []
        for relation, a, b in triples:
            winner = conflict_winner(a, b)
            loser = b if winner is a else a
            out.append(
                Conflict(
                    id=relation.id,
                    a=sides[a.id],
                    b=sides[b.id],
                    detected_at=relation.created_at,
                    similarity=float(relation.confidence),
                    detail=relation.detail,
                    suggested_winner_id=winner.id,
                    rationale=rationale(winner, loser),
                    status="open",
                )
            )
        return out
    records = list(
        await session.scalars(
            select(ConflictResolution)
            .where(ConflictResolution.project_id == viewer.project_id)
            .order_by(ConflictResolution.created_at.desc())
            .limit(200)
        )
    )
    items = await _items(session, {r.a_id for r in records} | {r.b_id for r in records})
    visible = [
        r
        for r in records
        if (a := items.get(r.a_id)) is not None
        and (b := items.get(r.b_id)) is not None
        and can_view(a, viewer)
        and can_view(b, viewer)
    ]
    sides = await _sides(session, viewer, list({i for r in visible for i in (items[r.a_id], items[r.b_id])}))
    result = []
    for r in visible:
        a, b = items[r.a_id], items[r.b_id]
        result.append(
            Conflict(
                id=r.relation_id,
                a=sides[a.id],
                b=sides[b.id],
                detected_at=r.detected_at,
                similarity=float(r.similarity),
                detail=r.detail,
                suggested_winner_id=r.winner_id or conflict_winner(a, b).id,
                rationale=r.reason or ("Arbitrée" if r.status == "resolved" else "Pas une contradiction"),
                status=r.status,  # type: ignore[arg-type]
                resolution=ConflictResolutionOut(
                    status=r.status,  # type: ignore[arg-type]
                    winner_id=r.winner_id,
                    reason=r.reason,
                    resolved_by=r.resolved_by_label,
                    resolved_at=r.created_at,
                ),
            )
        )
    return result


async def _open_conflict(
    session: AsyncSession, access: ProjectAccess, conflict_id: uuid.UUID
) -> tuple[Relation, MemoryItem, MemoryItem]:
    viewer = MemoryViewer.from_access(access)
    relation = await session.get(Relation, conflict_id)
    if relation is None or relation.project_id != access.project_id:
        if await session.get(ConflictResolution, conflict_id) is not None:
            raise conflict("Cette contradiction a déjà été traitée")
        raise not_found(CONFLICT_NOT_FOUND)
    if relation.rel_type != RelationType.contradicts:
        raise not_found(CONFLICT_NOT_FOUND)
    a = await _mutable(session, access, relation.src_id)
    b = await _mutable(session, access, relation.dst_id)
    if not (can_view(a, viewer) and can_view(b, viewer)):
        raise not_found(CONFLICT_NOT_FOUND)
    return relation, a, b


def _record(
    relation: Relation,
    a: MemoryItem,
    b: MemoryItem,
    access: ProjectAccess,
    status: str,
    winner_id: uuid.UUID | None,
    reason: str | None,
) -> ConflictResolution:
    return ConflictResolution(
        relation_id=relation.id,
        project_id=access.project_id,
        a_id=a.id,
        b_id=b.id,
        status=status,
        winner_id=winner_id,
        reason=reason,
        similarity=float(relation.confidence),
        detail=relation.detail,
        detected_at=relation.created_at,
        resolved_by_label=access.principal.label,
        resolved_by_id=access.principal.id,
    )


async def resolve(
    session: AsyncSession,
    access: ProjectAccess,
    conflict_id: uuid.UUID,
    winner_id: uuid.UUID,
    reason: str | None,
) -> Conflict:
    relation, a, b = await _open_conflict(session, access, conflict_id)
    if winner_id in (a.id, a.lineage_id):
        winner, loser = a, b
    elif winner_id in (b.id, b.lineage_id):
        winner, loser = b, a
    else:
        raise validation_error("Le gagnant doit être l'un des deux items de la contradiction")
    text = reason or f"Contradiction arbitrée : {_quote(winner.title)} conservé"
    session.add(_record(relation, a, b, access, "resolved", winner.id, reason))
    await lifecycle.supersede(session, loser, winner, access.principal.actor, text)
    # The supersession deleted the ``contradicts`` edge; make sure it is gone even if it was reversed.
    await session.execute(
        delete(Relation)
        .where(Relation.id == relation.id, Relation.rel_type == RelationType.contradicts)
        .execution_options(synchronize_session=False)
    )
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        audit.AuditAction.memory_conflict_resolved,
        "memory",
        winner.id,
        summary=f"Contradiction arbitrée : {_quote(winner.title)} conservé, {_quote(loser.title)} remplacé",
        details={"conflict_id": relation.id, "winner_id": winner.id, "loser_id": loser.id, "reason": reason},
    )
    await session.commit()
    return await _one(session, access, conflict_id)


async def dismiss(
    session: AsyncSession, access: ProjectAccess, conflict_id: uuid.UUID, reason: str | None
) -> Conflict:
    relation, a, b = await _open_conflict(session, access, conflict_id)
    session.add(_record(relation, a, b, access, "dismissed", None, reason or "Pas une contradiction"))
    duplicate = await session.scalar(
        select(Relation.id).where(
            Relation.rel_type == RelationType.relates_to,
            or_(
                and_(Relation.src_id == a.id, Relation.dst_id == b.id),
                and_(Relation.src_id == b.id, Relation.dst_id == a.id),
            ),
        )
    )
    if duplicate is not None:
        await session.delete(relation)
    else:
        relation.rel_type = RelationType.relates_to
        relation.detail = "Contradiction écartée (pas une contradiction)" + (f" : {reason}" if reason else "")
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        audit.AuditAction.memory_conflict_dismissed,
        "memory",
        a.id,
        summary=f"Contradiction écartée entre {_quote(a.title)} et {_quote(b.title)}",
        details={"conflict_id": relation.id, "items": [a.id, b.id], "reason": reason},
    )
    await session.commit()
    return await _one(session, access, conflict_id)


async def _one(session: AsyncSession, access: ProjectAccess, conflict_id: uuid.UUID) -> Conflict:
    for item in await list_conflicts(session, MemoryViewer.from_access(access), "resolved"):
        if item.id == conflict_id:
            return item
    raise not_found(CONFLICT_NOT_FOUND)
