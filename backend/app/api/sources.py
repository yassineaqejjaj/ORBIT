"""Business sources: list with per-source counts (only documents visible to the caller), create, patch.

Audit actions: ``source.create`` / ``source.update``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import EditorAccess, SessionDep, ViewerAccess
from app.enums import DocumentStatus, classification_code
from app.errors import conflict
from app.ingestion.service import DocumentViewer, get_project_source
from app.models import Document
from app.models import Source as SourceModel
from app.schemas import Source, SourceCreateIn, SourceUpdateIn
from app.schemas.documents import SourceCounts
from app.services import audit
from app.services.audit import AuditAction

router = APIRouter(prefix="/projects/{slug}/sources", tags=["sources"])


async def _counts(session: AsyncSession, viewer: DocumentViewer) -> dict[uuid.UUID, SourceCounts]:
    rows = await session.execute(
        select(Document.source_id, Document.status, func.count())
        .where(viewer.clause(), Document.status != DocumentStatus.forgotten)
        .group_by(Document.source_id, Document.status)
    )
    counts: dict[uuid.UUID, SourceCounts] = {}
    for source_id, doc_status, n in rows.tuples():
        entry = counts.setdefault(source_id, SourceCounts())
        entry.documents += n
        if doc_status == DocumentStatus.indexed:
            entry.indexed += n
        elif doc_status == DocumentStatus.failed:
            entry.failed += n
        elif doc_status in (DocumentStatus.pending, DocumentStatus.processing):
            entry.processing += n
    return counts


def _to_schema(source: SourceModel, counts: SourceCounts | None = None) -> Source:
    return Source.model_validate(source).model_copy(update={"counts": counts or SourceCounts()})


async def _ensure_unique_name(
    session: AsyncSession, project_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    stmt = select(SourceModel.id).where(
        SourceModel.project_id == project_id, func.lower(SourceModel.name) == name.lower()
    )
    if exclude is not None:
        stmt = stmt.where(SourceModel.id != exclude)
    if await session.scalar(stmt.limit(1)) is not None:
        raise conflict(f"Une source nommée « {name} » existe déjà dans ce projet")


@router.get("", response_model=list[Source], summary="Sources du projet")
async def list_sources(access: ViewerAccess, session: SessionDep) -> list[Source]:
    sources = list(
        await session.scalars(
            select(SourceModel)
            .where(SourceModel.project_id == access.project_id)
            .order_by(SourceModel.kind, SourceModel.name)
        )
    )
    counts = await _counts(session, DocumentViewer.from_access(access))
    return [_to_schema(s, counts.get(s.id)) for s in sources]


@router.post("", response_model=Source, status_code=status.HTTP_201_CREATED, summary="Créer une source")
async def create_source(body: SourceCreateIn, access: EditorAccess, session: SessionDep) -> Source:
    await _ensure_unique_name(session, access.project_id, body.name)
    source = SourceModel(
        project_id=access.project_id,
        name=body.name,
        kind=body.kind,
        description=body.description,
        default_classification=body.default_classification,
        default_acl=list(body.default_acl),
        config=dict(body.config),
    )
    session.add(source)
    await session.flush()
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.source_create,
        "source",
        source.id,
        summary=(
            f"Création de la source « {source.name} » "
            f"({classification_code(source.default_classification)} par défaut)"
        ),
        details={
            "kind": source.kind.value,
            "default_classification": source.default_classification,
            "default_acl": source.default_acl,
        },
    )
    await session.commit()
    await session.refresh(source)
    return _to_schema(source)


@router.patch("/{source_id}", response_model=Source, summary="Modifier une source")
async def update_source(
    source_id: uuid.UUID, body: SourceUpdateIn, access: EditorAccess, session: SessionDep
) -> Source:
    source = await get_project_source(session, access.project_id, source_id)
    changes: dict[str, dict[str, Any]] = {}
    values = body.model_dump(exclude_unset=True)
    for key, value in values.items():
        if value is None:
            continue
        if key == "name" and value != source.name:
            await _ensure_unique_name(session, access.project_id, value, exclude=source.id)
        current = getattr(source, key)
        if current != value:
            changes[key] = {"from": current, "to": value}
            setattr(source, key, value)
    if changes:
        await audit.record(
            session,
            access.project_id,
            access.principal,
            AuditAction.source_update,
            "source",
            source.id,
            summary=f"Modification de la source « {source.name} » ({', '.join(changes)})",
            details={"changes": changes},
        )
        await session.commit()
        await session.refresh(source)
    counts = await _counts(session, DocumentViewer.from_access(access))
    return _to_schema(source, counts.get(source.id))
