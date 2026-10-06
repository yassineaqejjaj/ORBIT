"""Documents (docs/API.md « Sources & documents »).

Upload / text / import accept agent keys. Every read is filtered by the caller's ACL principals and
clearance (:class:`app.ingestion.service.DocumentViewer`): an inaccessible document is a ``404`` and is
absent from lists and counts. ``PiiEntity.text`` is omitted — and chunk text replaced by its redacted
form — for callers below ``editor`` and for agents. Every mutation writes an audit event.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.deps import AgentEditorAccess, EditorAccess, OwnerAccess, ProjectAccess, SessionDep, ViewerAccess
from app.enums import (
    ChunkStatus,
    DocumentStatus,
    JobKind,
    JobStatus,
    SourceKind,
    TombstoneTarget,
    classification_code,
)
from app.errors import ApiError, conflict, not_found, validation_error
from app.ingestion.extractors import MARKDOWN, SUPPORTED_FORMATS_LABEL, detect_mime_type, is_supported
from app.ingestion.importers import RecordParseError, map_records, parse_records
from app.ingestion.pipeline import FORGOTTEN_TEXT, actor_payload
from app.ingestion.queue import enqueue_job
from app.ingestion.service import (
    ContentIn,
    DocumentViewer,
    get_visible_document,
    ingest_content,
    parse_acl_field,
    parse_tags_csv,
    resolve_source,
    serialize_summaries,
    serialize_summary,
    sync_index_metadata,
    title_from_filename,
)
from app.memory.serializers import serialize_items
from app.memory.visibility import MemoryViewer, visibility_clause
from app.models import Chunk, Document, IngestionJob, MemoryItem, MemoryProvenance, Source, Tombstone
from app.models import DocumentVersion as DocumentVersionModel
from app.schemas import (
    DocumentDetail,
    DocumentSummary,
    DocumentUpdateIn,
    ForgetIn,
    ImportResult,
    Job,
    Page,
    PageParams,
    TextDocumentIn,
    page_params,
)
from app.schemas.common import make_page
from app.schemas.documents import ChunkView, DocumentVersion, PiiEntity, QuarantinedChunk
from app.search import opensearch
from app.services import audit
from app.services.audit import AuditAction
from app.storage.object_store import ObjectNotFoundError, ObjectStoreError, get_object_store

logger = logging.getLogger("orbit.api.documents")

router = APIRouter(prefix="/projects/{slug}/documents", tags=["documents"])

MAX_FILES_PER_UPLOAD = 50
DETAIL_JOBS_LIMIT = 20


def _storage_unavailable(exc: Exception) -> ApiError:
    return ApiError(503, f"Stockage des fichiers indisponible : {exc}", code="service_unavailable")


def _too_large(name: str) -> ApiError:
    return validation_error(
        f"Le fichier « {name} » dépasse la taille maximale autorisée ({settings.max_upload_mb} Mo)"
    )


async def _read_upload(upload: UploadFile) -> bytes:
    name = upload.filename or "fichier"
    data = await upload.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise _too_large(name)
    if not data:
        raise validation_error(f"Le fichier « {name} » est vide")
    return data


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --- List ---------------------------------------------------------------------------------------------


@router.get("", response_model=Page[DocumentSummary], summary="Documents du projet (filtrés par droits)")
async def list_documents(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    source_id: uuid.UUID | None = Query(default=None),
    status_: DocumentStatus | None = Query(default=None, alias="status"),
    source_kind: SourceKind | None = Query(default=None),
    classification: int | None = Query(default=None, ge=0, le=3),
    q: str | None = Query(default=None, max_length=200),
) -> Page[DocumentSummary]:
    viewer = DocumentViewer.from_access(access)
    conditions: list[Any] = [viewer.clause()]
    if source_id is not None:
        conditions.append(Document.source_id == source_id)
    if status_ is not None:
        conditions.append(Document.status == status_)
    if classification is not None:
        conditions.append(Document.classification == classification)
    if source_kind is not None:
        conditions.append(
            Document.source_id.in_(
                select(Source.id).where(Source.project_id == access.project_id, Source.kind == source_kind)
            )
        )
    if q and q.strip():
        conditions.append(Document.title.ilike(f"%{_escape_like(q.strip())}%", escape="\\"))
    total = int(await session.scalar(select(func.count()).select_from(Document).where(*conditions)) or 0)
    documents = list(
        await session.scalars(
            select(Document)
            .where(*conditions)
            .order_by(Document.updated_at.desc(), Document.id)
            .offset(params.offset)
            .limit(params.limit)
        )
    )
    return make_page(await serialize_summaries(session, documents), total, params)


# --- Ingestion ----------------------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=list[DocumentSummary],
    status_code=status.HTTP_201_CREATED,
    summary="Téléverser des fichiers (statut pending)",
)
async def upload_documents(
    access: AgentEditorAccess,
    session: SessionDep,
    files: list[UploadFile] = File(..., description="Fichiers (PDF, DOCX, Markdown, texte, HTML, JSON, CSV)"),
    source_id: uuid.UUID | None = Form(default=None),
    classification: int | None = Form(default=None, ge=0, le=3),
    acl_principals: str | None = Form(default=None, description="CSV, ex. role:editor,user:<uuid>"),
    tags: str | None = Form(default=None, description="CSV"),
) -> list[DocumentSummary]:
    if not files:
        raise validation_error("Aucun fichier reçu")
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise validation_error(f"Trop de fichiers dans un même envoi (maximum {MAX_FILES_PER_UPLOAD})")
    acl = parse_acl_field(acl_principals)
    tag_list = parse_tags_csv(tags)

    # Validate every file before writing anything (all-or-nothing).
    contents: list[ContentIn] = []
    for upload in files:
        name = upload.filename or "fichier"
        data = await _read_upload(upload)
        mime_type = detect_mime_type(upload.filename, upload.content_type, data)
        if not is_supported(mime_type, upload.filename):
            from app.ingestion.extractors import markitdown

            accepted = SUPPORTED_FORMATS_LABEL + (
                f", {markitdown.CONVERTIBLE_LABEL} (via MarkItDown)" if markitdown.available() else ""
            )
            raise validation_error(
                f"Format non pris en charge pour « {name} » (formats acceptés : {accepted})"
            )
        contents.append(
            ContentIn(
                title=title_from_filename(upload.filename),
                mime_type=mime_type,
                data=data,
                filename=upload.filename or None,
                classification=classification,
                acl_principals=acl,
                tags=tag_list,
            )
        )

    source = await resolve_source(
        session, access.project_id, source_id, SourceKind.document, access.principal.actor
    )
    documents: list[Document] = []
    try:
        for content in contents:
            outcome = await ingest_content(session, access, source, content)
            documents.append(outcome.document)
    except ObjectStoreError as exc:
        await session.rollback()
        raise _storage_unavailable(exc) from exc
    await session.commit()
    for document in documents:
        await session.refresh(document)
    return await serialize_summaries(session, documents)


@router.post(
    "/text", response_model=DocumentSummary, status_code=status.HTTP_201_CREATED, summary="Ingérer un texte"
)
async def create_text_document(
    body: TextDocumentIn, access: AgentEditorAccess, session: SessionDep
) -> DocumentSummary:
    source = await resolve_source(
        session,
        access.project_id,
        body.source_id,
        body.source_kind or SourceKind.note,
        access.principal.actor,
    )
    outcome = await ingest_content(
        session,
        access,
        source,
        ContentIn(
            title=body.title,
            mime_type=MARKDOWN,
            text=body.content,
            external_id=body.external_id or None,
            uri=body.uri or None,
            author=body.author or None,
            classification=body.classification,
            acl_principals=body.acl_principals,
            tags=body.tags,
            source_updated_at=body.source_updated_at,
            metadata=dict(body.metadata or {}),
        ),
    )
    await session.commit()
    await session.refresh(outcome.document)
    return await serialize_summary(session, outcome.document)


@router.post(
    "/import",
    response_model=ImportResult,
    summary="Importer des tickets / CRM / retours / traces (JSON ou CSV)",
)
async def import_documents(
    access: AgentEditorAccess,
    session: SessionDep,
    file: UploadFile = File(...),
    source_kind: SourceKind = Form(...),
    source_id: uuid.UUID | None = Form(default=None),
) -> ImportResult:
    data = await _read_upload(file)
    try:
        records = map_records(parse_records(data, file.filename, file.content_type), source_kind)
    except RecordParseError as exc:
        raise validation_error(str(exc)) from exc
    source = await resolve_source(session, access.project_id, source_id, source_kind, access.principal.actor)

    created = updated = 0
    documents: dict[uuid.UUID, Document] = {}
    for record in records:
        outcome = await ingest_content(
            session,
            access,
            source,
            ContentIn(
                title=record.title,
                mime_type=MARKDOWN,
                text=record.content,
                external_id=record.external_id,
                uri=record.uri,
                author=record.author,
                classification=record.classification,
                tags=record.tags or None,
                source_updated_at=record.source_updated_at,
                metadata=record.metadata,
            ),
            audit_event=False,
        )
        if outcome.created:
            created += 1
        elif outcome.new_version:
            updated += 1
        documents[outcome.document.id] = outcome.document
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.document_import,
        "source",
        source.id,
        summary=(
            f"Import de {len(records)} enregistrement(s) dans « {source.name} » : "
            f"{created} créé(s), {updated} mis à jour"
        ),
        details={
            "filename": file.filename,
            "source_kind": source_kind.value,
            "records": len(records),
            "created": created,
            "updated": updated,
            "unchanged": len(records) - created - updated,
        },
    )
    await session.commit()
    docs = list(documents.values())
    for document in docs:
        await session.refresh(document)
    return ImportResult(created=created, updated=updated, documents=await serialize_summaries(session, docs))


# --- Detail -------------------------------------------------------------------------------------------


def _chunk_view(chunk: Chunk, *, can_see_pii: bool) -> ChunkView:
    entities = [
        PiiEntity(
            type=entry["type"],
            start=int(entry.get("start", 0)),
            end=int(entry.get("end", 0)),
            text=entry.get("text") if can_see_pii else None,
        )
        for entry in (chunk.pii or [])
        if isinstance(entry, dict) and entry.get("type")
    ]
    text = chunk.text if can_see_pii or not entities else chunk.text_redacted
    return ChunkView(
        id=chunk.id,
        version=chunk.version,
        ordinal=chunk.ordinal,
        text=text,
        text_redacted=chunk.text_redacted,
        token_count=chunk.token_count,
        section=chunk.section,
        pii=entities,
        classification=chunk.classification,
        status=chunk.status,
        injection_score=float(chunk.injection_score or 0.0),
        injection_reasons=list(chunk.injection_reasons or []),
        quarantined=bool(chunk.quarantined),
        quarantine_released_at=chunk.quarantine_released_at,
    )


async def _derived_memory(session: AsyncSession, access: ProjectAccess, document_id: uuid.UUID) -> list[Any]:
    viewer = MemoryViewer.from_access(access)
    item_ids = select(MemoryProvenance.memory_item_id).where(MemoryProvenance.document_id == document_id)
    items = list(
        await session.scalars(
            select(MemoryItem)
            .where(MemoryItem.id.in_(item_ids), MemoryItem.is_current.is_(True), visibility_clause(viewer))
            .order_by(MemoryItem.created_at)
        )
    )
    return await serialize_items(session, items)


@router.get(
    "/quarantine",
    response_model=list[QuarantinedChunk],
    summary="Fragments en quarantaine (injection de prompt suspectée, propriétaires)",
)
async def list_quarantine(access: OwnerAccess, session: SessionDep) -> list[QuarantinedChunk]:
    rows = await session.execute(
        select(Chunk, Document.title)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.project_id == access.project_id,
            Chunk.quarantined.is_(True),
            Chunk.status == ChunkStatus.active,
            Document.status != DocumentStatus.forgotten,
        )
        .order_by(Chunk.injection_score.desc(), Chunk.created_at.desc())
        .limit(200)
    )
    return [
        QuarantinedChunk(
            id=c.id,
            document_id=c.document_id,
            document_title=title,
            version=c.version,
            ordinal=c.ordinal,
            section=c.section,
            text=c.text_redacted,
            injection_score=float(c.injection_score or 0.0),
            injection_reasons=list(c.injection_reasons or []),
            created_at=c.created_at,
        )
        for c, title in rows.tuples()
    ]


@router.get("/{document_id}", response_model=DocumentDetail, summary="Détail d'un document")
async def get_document(document_id: uuid.UUID, access: ViewerAccess, session: SessionDep) -> DocumentDetail:
    viewer = DocumentViewer.from_access(access)
    document = await get_visible_document(session, viewer, document_id)
    summary = await serialize_summary(session, document)
    versions = [
        DocumentVersion(
            id=v.id,
            version=v.version,
            content_hash=v.content_hash,
            size_bytes=v.size_bytes,
            created_at=v.created_at,
            char_count=int((v.metadata_ or {}).get("char_count") or len(v.extracted_text or "")),
        )
        for v in await session.scalars(
            select(DocumentVersionModel)
            .where(DocumentVersionModel.document_id == document.id)
            .order_by(DocumentVersionModel.version.desc())
        )
    ]
    chunks = [
        _chunk_view(c, can_see_pii=viewer.can_see_pii)
        for c in await session.scalars(
            select(Chunk)
            .where(Chunk.document_id == document.id, Chunk.version == document.current_version)
            .order_by(Chunk.ordinal)
        )
    ]
    jobs = [
        Job.model_validate(j)
        for j in await session.scalars(
            select(IngestionJob)
            .where(IngestionJob.document_id == document.id)
            .order_by(IngestionJob.created_at.desc())
            .limit(DETAIL_JOBS_LIMIT)
        )
    ]
    return DocumentDetail.model_validate(
        {
            **summary.model_dump(),
            "metadata": dict(document.metadata_ or {}),
            "versions": versions,
            "chunks": chunks,
            "jobs": jobs,
            "memory_items": await _derived_memory(session, access, document.id),
            "forgotten_at": document.forgotten_at,
            "forgotten_by": document.forgotten_by,
        }
    )


# --- Mutations ----------------------------------------------------------------------------------------


@router.patch(
    "/{document_id}",
    response_model=DocumentSummary,
    summary="Modifier titre, classification, ACL, étiquettes",
)
async def update_document(
    document_id: uuid.UUID, body: DocumentUpdateIn, access: EditorAccess, session: SessionDep
) -> DocumentSummary:
    document = await get_visible_document(session, DocumentViewer.from_access(access), document_id)
    if document.status == DocumentStatus.forgotten:
        raise conflict("Ce document a été oublié : il ne peut plus être modifié")
    values = body.model_dump(exclude_unset=True)
    changes: dict[str, dict[str, Any]] = {}
    for key in ("title", "classification", "acl_principals", "tags"):
        value = values.get(key)
        if value is None:
            continue
        current = getattr(document, key)
        current_cmp = list(current or []) if isinstance(value, list) else current
        if current_cmp != value:
            changes[key] = {"from": current_cmp, "to": value}
            setattr(document, key, value)
    if not changes:
        return await serialize_summary(session, document)

    if "classification" in changes:
        # An explicit classification is authoritative: the pipeline will not raise it automatically.
        document.metadata_ = {**(document.metadata_ or {}), "classification_manual": True}
    document.updated_at = utcnow()
    source = await session.get(Source, document.source_id)
    await sync_index_metadata(session, document, source)

    actor = access.principal
    await audit.record(
        session,
        access.project_id,
        actor,
        AuditAction.document_update,
        "document",
        document.id,
        summary=f"Modification de « {document.title} » ({', '.join(changes)})",
        details={"changes": changes},
    )
    if "acl_principals" in changes:
        await audit.record(
            session,
            access.project_id,
            actor,
            AuditAction.acl_change,
            "document",
            document.id,
            summary=f"ACL de « {document.title} » : {', '.join(document.acl_principals)}",
            details=changes["acl_principals"],
        )
    if "classification" in changes:
        before = changes["classification"]["from"]
        await audit.record(
            session,
            access.project_id,
            actor,
            AuditAction.classification_change,
            "document",
            document.id,
            summary=(
                f"Classification de « {document.title} » : {classification_code(before)} → "
                f"{classification_code(document.classification)}"
            ),
            details={**changes["classification"], "automatic": False},
        )
    await session.commit()
    await session.refresh(document)
    return await serialize_summary(session, document)


@router.post("/{document_id}/reprocess", response_model=Job, summary="Relancer le traitement")
async def reprocess_document(document_id: uuid.UUID, access: EditorAccess, session: SessionDep) -> Job:
    document = await get_visible_document(session, DocumentViewer.from_access(access), document_id)
    if document.status == DocumentStatus.forgotten:
        raise conflict("Ce document a été oublié : il ne peut plus être retraité")
    pending = await session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document.id,
            IngestionJob.kind == JobKind.ingest,
            IngestionJob.status.in_([JobStatus.queued, JobStatus.running]),
        )
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    if pending is not None:
        return Job.model_validate(pending)
    actor = access.principal.actor
    job = await enqueue_job(
        session,
        access.project_id,
        JobKind.ingest,
        document.id,
        payload={"version": document.current_version, "actor": actor_payload(actor), "reprocess": True},
    )
    document.status = DocumentStatus.pending
    document.status_reason = None
    await audit.record(
        session,
        access.project_id,
        actor,
        AuditAction.document_reprocess,
        "document",
        document.id,
        summary=f"Retraitement de « {document.title} » (v{document.current_version})",
        details={"job_id": str(job.id), "version": document.current_version},
    )
    await session.commit()
    await session.refresh(job)
    return Job.model_validate(job)


@router.post("/{document_id}/forget", response_model=DocumentSummary, summary="Oubli sélectif d'un document")
async def forget_document(
    document_id: uuid.UUID, body: ForgetIn, access: OwnerAccess, session: SessionDep
) -> DocumentSummary:
    document = await get_visible_document(session, DocumentViewer.from_access(access), document_id)
    if document.status == DocumentStatus.forgotten:
        raise conflict("Ce document a déjà été oublié")
    principal = access.principal
    now = utcnow()
    tombstone = Tombstone(
        project_id=access.project_id,
        target_type=TombstoneTarget.document,
        target_id=document.id,
        reason=body.reason,
        requested_by=principal.user_id,
    )
    session.add(tombstone)
    document.status = DocumentStatus.forgotten
    document.status_reason = None
    document.forgotten_at = now
    document.forgotten_by = principal.user_id
    # Immediate effect in Postgres; the ``forget`` job purges the index, raw files and derived memory.
    await session.execute(
        update(Chunk)
        .where(Chunk.document_id == document.id)
        .values(status=ChunkStatus.forgotten, text=FORGOTTEN_TEXT, text_redacted=FORGOTTEN_TEXT, pii=[])
    )
    await session.flush()
    job = await enqueue_job(
        session,
        access.project_id,
        JobKind.forget,
        document.id,
        payload={
            "tombstone_id": str(tombstone.id),
            "actor": actor_payload(principal.actor),
            "reason": body.reason,
        },
    )
    await audit.record(
        session,
        access.project_id,
        principal,
        AuditAction.document_forget,
        "document",
        document.id,
        summary=f"Oubli sélectif de « {document.title} »",
        details={"reason": body.reason, "tombstone_id": str(tombstone.id), "job_id": str(job.id)},
    )
    await session.commit()
    try:
        await opensearch.delete_by_query("chunks", {"term": {"document_id": str(document.id)}}, refresh=True)
    except Exception as exc:  # the forget job deletes them anyway; search also re-checks Postgres
        logger.warning("Immediate index purge of forgotten document %s failed: %s", document.id, exc)
    await session.refresh(document)
    return await serialize_summary(session, document)


@router.post(
    "/{document_id}/chunks/{chunk_id}/release",
    response_model=ChunkView,
    summary="Libérer un fragment de la quarantaine (propriétaire, audité)",
)
async def release_quarantine(
    document_id: uuid.UUID, chunk_id: uuid.UUID, access: OwnerAccess, session: SessionDep
) -> ChunkView:
    document = await get_visible_document(session, DocumentViewer.from_access(access), document_id)
    chunk = await session.get(Chunk, chunk_id)
    if chunk is None or chunk.document_id != document.id:
        raise not_found("Fragment introuvable")
    if not chunk.quarantined:
        raise conflict("Ce fragment n'est pas en quarantaine")
    chunk.quarantined = False
    chunk.quarantine_released_at = utcnow()
    chunk.quarantine_released_by = access.principal.user_id
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.quarantine_release,
        "chunk",
        chunk.id,
        summary=f"Fragment n°{chunk.ordinal + 1} de « {document.title} » libéré de la quarantaine",
        details={
            "document_id": str(document.id),
            "version": chunk.version,
            "score": float(chunk.injection_score or 0.0),
            "reasons": [r.get("code") for r in chunk.injection_reasons or []],
        },
    )
    # The released extract may now feed the memory (extraction skipped quarantined chunks).
    await enqueue_job(
        session, access.project_id, JobKind.extract_memory, document.id, payload={"version": chunk.version}
    )
    await session.commit()
    return _chunk_view(chunk, can_see_pii=DocumentViewer.from_access(access).can_see_pii)


# --- Raw file -----------------------------------------------------------------------------------------


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode() or "document"
    ascii_name = ascii_name.replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get(
    "/{document_id}/raw",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "Fichier original"}},
    summary="Télécharger le fichier original",
)
async def get_document_raw(document_id: uuid.UUID, access: EditorAccess, session: SessionDep) -> Response:
    document = await get_visible_document(session, DocumentViewer.from_access(access), document_id)
    if document.status == DocumentStatus.forgotten:
        raise not_found("Fichier original supprimé : le document a été oublié")
    version = await session.scalar(
        select(DocumentVersionModel).where(
            DocumentVersionModel.document_id == document.id,
            DocumentVersionModel.version == document.current_version,
        )
    )
    if version is None:
        raise not_found("Version courante du document introuvable")
    filename = str((version.metadata_ or {}).get("filename") or "")
    if version.object_key:
        try:
            data = await get_object_store().get(version.object_key)
        except ObjectNotFoundError as exc:
            raise not_found("Fichier original introuvable dans le stockage") from exc
        except ObjectStoreError as exc:
            raise _storage_unavailable(exc) from exc
        media_type = document.mime_type or "application/octet-stream"
    else:
        data = (version.extracted_text or "").encode("utf-8")
        media_type = "text/markdown; charset=utf-8"
        filename = filename or f"{document.title}.md"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": _content_disposition(filename or document.title)},
    )
