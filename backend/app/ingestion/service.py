"""Document access rules and write operations shared by the sources / documents / jobs / search routers.

* :class:`DocumentViewer` — which documents a caller may see (ACL principals + clearance, §3). Documents
  outside it are invisible everywhere: lists, counts, jobs, search hits, and ``404`` on detail.
* :func:`ingest_content` — create a document (or a new version of an existing one: same
  ``external_id`` in the source, or same title in the source), store the payload, set the document
  ``pending`` and enqueue an ``ingest`` job.
* :func:`serialize_summaries` — ``DocumentSummary`` with source name/kind and active chunk count.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import ColumnElement, Text, and_, func, select, update
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import ChunkStatus, DocumentStatus, JobKind, Role, SourceKind, classification_code
from app.errors import conflict, not_found, validation_error
from app.governance.acl import (
    acl_allows,
    classification_allowed,
    effective_principals,
    parse_acl_csv,
    validate_acl_principals,
)
from app.ingestion.extractors import MARKDOWN
from app.ingestion.pipeline import actor_payload, document_index_fields
from app.ingestion.queue import enqueue_job
from app.models import Chunk, Document, DocumentVersion, IngestionJob, Source
from app.schemas import DocumentSummary
from app.schemas.common import Tags
from app.search import opensearch
from app.services import audit
from app.services.audit import Actor, AuditAction
from app.storage.object_store import get_object_store, make_key, sha256_bytes, sha256_text

if TYPE_CHECKING:
    from app.deps import ProjectAccess

logger = logging.getLogger("orbit.documents")

#: Names of the sources created on the fly when content is pushed without ``source_id``.
DEFAULT_SOURCE_NAMES: dict[SourceKind, str] = {
    SourceKind.document: "Documents",
    SourceKind.note: "Notes",
    SourceKind.ticket: "Tickets",
    SourceKind.crm: "CRM",
    SourceKind.feedback: "Retours utilisateurs",
    SourceKind.agent_trace: "Traces agents",
    SourceKind.url: "Web",
}

#: Keys of ``Document.metadata_`` written by the platform itself (never overwritten by callers).
RESERVED_METADATA_KEYS = frozenset({"classification_manual", "classification_reasons"})

#: Statuses for which re-sending identical content is a no-op (no new version).
_DEDUP_STATUSES = frozenset({DocumentStatus.pending, DocumentStatus.processing, DocumentStatus.indexed})

_TAGS = TypeAdapter(Tags)


# --- Visibility -----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentViewer:
    """Visibility parameters of a caller on the documents of one project."""

    project_id: uuid.UUID
    principals: frozenset[str]
    clearance: int
    is_admin: bool
    can_see_pii: bool

    @classmethod
    def from_access(cls, access: ProjectAccess) -> DocumentViewer:
        principal = access.principal
        return cls(
            project_id=access.project_id,
            principals=frozenset(effective_principals(access)),
            clearance=int(principal.clearance),
            is_admin=principal.is_user and principal.is_admin,
            # Agents always receive redacted text (§3 « Données personnelles »).
            can_see_pii=principal.is_user and access.has_role(Role.editor),
        )

    def allows(self, acl_principals: Sequence[str] | None, classification: int) -> bool:
        if self.is_admin:
            return True
        return classification_allowed(classification, self.clearance) and acl_allows(
            acl_principals, self.principals
        )

    def can_view(self, document: Document) -> bool:
        return document.project_id == self.project_id and self.allows(
            document.acl_principals, int(document.classification)
        )

    def clause(self) -> ColumnElement[bool]:
        """SQL condition selecting the documents of the project visible to this caller."""
        in_project = Document.project_id == self.project_id
        if self.is_admin:
            return in_project
        principals = sorted(self.principals) or ["__none__"]
        return and_(
            in_project,
            Document.classification <= self.clearance,
            Document.acl_principals.overlap(array(principals, type_=Text)),
        )

    def search_filters(self) -> list[dict[str, Any]]:
        """OpenSearch pre-filters equivalent to :meth:`clause` (plus active chunks only)."""
        clauses: list[dict[str, Any]] = [{"term": {"status": ChunkStatus.active.value}}]
        if not self.is_admin:
            clauses.append({"range": {"classification": {"lte": self.clearance}}})
            clauses.append({"terms": {"acl_principals": sorted(self.principals) or ["__none__"]}})
        return clauses


async def get_visible_document(
    session: AsyncSession, viewer: DocumentViewer, document_id: uuid.UUID
) -> Document:
    """The document if the caller may see it, else ``404`` (existence is never revealed)."""
    document = await session.get(Document, document_id)
    if document is None or not viewer.can_view(document):
        raise not_found("Document introuvable")
    return document


# --- Serialization --------------------------------------------------------------------------------------


async def serialize_summaries(session: AsyncSession, documents: Sequence[Document]) -> list[DocumentSummary]:
    """``DocumentSummary`` list (2 extra queries: sources and active chunk counts)."""
    if not documents:
        return []
    source_ids = {d.source_id for d in documents}
    sources = {s.id: s for s in await session.scalars(select(Source).where(Source.id.in_(source_ids)))}
    doc_ids = [d.id for d in documents]
    counts = dict(
        (
            await session.execute(
                select(Chunk.document_id, func.count())
                .where(Chunk.document_id.in_(doc_ids), Chunk.status == ChunkStatus.active)
                .group_by(Chunk.document_id)
            )
        ).tuples()
    )
    summaries: list[DocumentSummary] = []
    for document in documents:
        source = sources.get(document.source_id)
        summaries.append(
            DocumentSummary.model_validate(document).model_copy(
                update={
                    "source_name": source.name if source is not None else "",
                    "source_kind": source.kind if source is not None else None,
                    "chunk_count": int(counts.get(document.id, 0)),
                }
            )
        )
    return summaries


async def serialize_summary(session: AsyncSession, document: Document) -> DocumentSummary:
    return (await serialize_summaries(session, [document]))[0]


# --- Input parsing --------------------------------------------------------------------------------------


def parse_tags_csv(raw: str | None) -> list[str] | None:
    if raw is None or not raw.strip():
        return None
    try:
        return _TAGS.validate_python([part for part in raw.split(",") if part.strip()])
    except ValidationError as exc:
        raise validation_error("Étiquettes invalides") from exc


def parse_acl_field(raw: str | None) -> list[str] | None:
    try:
        return parse_acl_csv(raw)
    except ValueError as exc:
        raise validation_error(str(exc)) from exc


def title_from_filename(filename: str | None) -> str:
    """``compte_rendu COPIL.v2.pdf`` → ``compte rendu COPIL.v2``."""
    name = PurePosixPath((filename or "").replace("\\", "/")).name
    stem = name.rsplit(".", 1)[0] if "." in name else name
    title = " ".join(stem.replace("_", " ").split())
    return (title or "Document sans titre")[:500]


def clean_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return {str(k): v for k, v in (metadata or {}).items() if str(k) not in RESERVED_METADATA_KEYS}


# --- Sources --------------------------------------------------------------------------------------------


async def get_project_source(session: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID) -> Source:
    source = await session.get(Source, source_id)
    if source is None or source.project_id != project_id:
        raise not_found("Source introuvable")
    return source


async def default_source(
    session: AsyncSession, project_id: uuid.UUID, kind: SourceKind, actor: Actor
) -> Source:
    """Default source of ``kind``: the one named after the kind, else the oldest one, else a new one."""
    name = DEFAULT_SOURCE_NAMES[kind]
    candidates = list(
        await session.scalars(
            select(Source)
            .where(Source.project_id == project_id, Source.kind == kind)
            .order_by(Source.created_at)
        )
    )
    for candidate in candidates:
        if candidate.name == name:
            return candidate
    if candidates:
        return candidates[0]
    source = Source(
        project_id=project_id,
        name=name,
        kind=kind,
        description="Source créée automatiquement lors d'une ingestion",
        default_classification=1,
        default_acl=["project:*"],
        config={"auto_created": True},
    )
    session.add(source)
    await session.flush()
    await audit.record(
        session,
        project_id,
        actor,
        AuditAction.source_create,
        "source",
        source.id,
        summary=f"Création automatique de la source « {name} »",
        details={"kind": kind.value, "auto_created": True},
    )
    return source


async def resolve_source(
    session: AsyncSession,
    project_id: uuid.UUID,
    source_id: uuid.UUID | None,
    kind: SourceKind | None,
    actor: Actor,
) -> Source:
    if source_id is not None:
        return await get_project_source(session, project_id, source_id)
    return await default_source(session, project_id, kind or SourceKind.document, actor)


# --- Ingestion ------------------------------------------------------------------------------------------


@dataclass(slots=True)
class ContentIn:
    """One piece of content to ingest (uploaded file, pushed text or imported record)."""

    title: str
    mime_type: str = MARKDOWN
    data: bytes | None = None  # raw file (stored in the object store)
    text: str | None = None  # pushed text (stored in the version row)
    filename: str | None = None
    external_id: str | None = None
    uri: str | None = None
    author: str | None = None
    classification: int | None = None
    acl_principals: list[str] | None = None
    tags: list[str] | None = None
    source_updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        if self.data is not None:
            return sha256_bytes(self.data)
        return sha256_text(self.text or "")

    @property
    def size_bytes(self) -> int:
        if self.data is not None:
            return len(self.data)
        return len((self.text or "").encode("utf-8"))


@dataclass(slots=True)
class IngestOutcome:
    document: Document
    created: bool
    new_version: bool
    job: IngestionJob | None


async def _find_existing(
    session: AsyncSession, project_id: uuid.UUID, source: Source, content: ContentIn
) -> Document | None:
    if content.external_id:
        return await session.scalar(
            select(Document).where(
                Document.project_id == project_id,
                Document.source_id == source.id,
                Document.external_id == content.external_id,
            )
        )
    return await session.scalar(
        select(Document)
        .where(
            Document.project_id == project_id,
            Document.source_id == source.id,
            Document.title == content.title,
            Document.external_id.is_(None),
            Document.status != DocumentStatus.forgotten,
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )


async def ingest_content(
    session: AsyncSession,
    access: ProjectAccess,
    source: Source,
    content: ContentIn,
    *,
    audit_event: bool = True,
) -> IngestOutcome:
    """Create or version a document from ``content`` and enqueue its ingestion (the caller commits)."""
    viewer = DocumentViewer.from_access(access)
    actor = access.principal.actor
    project_id = access.project_id
    existing = await _find_existing(session, project_id, source, content)
    if existing is not None and existing.status == DocumentStatus.forgotten:
        raise conflict(
            f"Le document « {content.external_id} » a fait l'objet d'un oubli sélectif : "
            "il ne peut pas être réingéré sous le même identifiant externe"
        )
    if existing is not None and not viewer.can_view(existing):
        if content.external_id:
            raise conflict(
                f"Un document portant l'identifiant externe « {content.external_id} » existe déjà dans "
                "cette source et ne vous est pas accessible"
            )
        existing = None  # same title but invisible: keep documents separate (non-leak)

    content_hash = content.content_hash
    if existing is not None:
        current = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == existing.id,
                DocumentVersion.version == existing.current_version,
            )
        )
        if (
            current is not None
            and current.content_hash == content_hash
            and existing.status in _DEDUP_STATUSES
        ):
            changed = _apply_metadata(existing, source, content, is_new=False)
            if changed and existing.status == DocumentStatus.indexed:
                await sync_index_metadata(session, existing, source)
            return IngestOutcome(document=existing, created=False, new_version=False, job=None)

    created = existing is None
    if existing is None:
        document = Document(
            project_id=project_id,
            source_id=source.id,
            external_id=content.external_id,
            title=content.title,
            mime_type=content.mime_type,
            classification=int(source.default_classification),
            acl_principals=list(source.default_acl or ["project:*"]),
            tags=[],
            metadata_={},
            status=DocumentStatus.pending,
            current_version=1,
            pii_count=0,
            source_updated_at=content.source_updated_at or utcnow(),
        )
        session.add(document)
        _apply_metadata(document, source, content, is_new=True)
        await session.flush()
        version_number = 1
    else:
        document = existing
        version_number = int(document.current_version) + 1
        document.current_version = version_number
        document.mime_type = content.mime_type
        document.title = content.title
        _apply_metadata(document, source, content, is_new=False)
        if content.source_updated_at is None:
            document.source_updated_at = utcnow()

    object_key: str | None = None
    if content.data is not None:
        object_key = make_key(project_id, document.id, version_number, content.filename)
        await get_object_store().put(object_key, content.data)
    version_meta: dict[str, Any] = {"content_type": content.mime_type}
    if content.filename:
        version_meta["filename"] = content.filename
    session.add(
        DocumentVersion(
            document_id=document.id,
            version=version_number,
            content_hash=content_hash,
            object_key=object_key,
            size_bytes=content.size_bytes,
            extracted_text=content.text or "",
            metadata_=version_meta,
        )
    )
    document.status = DocumentStatus.pending
    document.status_reason = None
    job = await enqueue_job(
        session,
        project_id,
        JobKind.ingest,
        document.id,
        payload={"version": version_number, "actor": actor_payload(actor)},
    )
    if audit_event:
        await audit.record(
            session,
            project_id,
            actor,
            AuditAction.document_ingest,
            "document",
            document.id,
            summary=(
                f"Ingestion de « {document.title} » ({classification_code(document.classification)})"
                if created
                else f"Nouvelle version v{version_number} de « {document.title} »"
            ),
            details={
                "source_id": str(source.id),
                "version": version_number,
                "mime_type": content.mime_type,
                "size_bytes": content.size_bytes,
                "classification": int(document.classification),
                "job_id": str(job.id),
            },
        )
    return IngestOutcome(document=document, created=created, new_version=not created, job=job)


def _apply_metadata(document: Document, source: Source, content: ContentIn, *, is_new: bool) -> bool:
    """Apply caller-provided metadata. Classification is never lowered here. Returns True if changed."""
    before = (
        document.classification,
        list(document.acl_principals or []),
        list(document.tags or []),
        document.author,
        document.uri,
        dict(document.metadata_ or {}),
    )
    if content.classification is not None:
        declared = int(content.classification)
        document.classification = declared if is_new else max(int(document.classification), declared)
    if content.acl_principals is not None:
        document.acl_principals = validate_acl_principals(content.acl_principals)
    elif is_new:
        document.acl_principals = list(source.default_acl or ["project:*"])
    if content.tags is not None:
        document.tags = list(content.tags)
    if content.author:
        document.author = content.author[:300]
    if content.uri:
        document.uri = content.uri
    if content.source_updated_at is not None:
        document.source_updated_at = content.source_updated_at
    extra = clean_metadata(content.metadata)
    if extra:
        document.metadata_ = {**(document.metadata_ or {}), **extra}
    after = (
        document.classification,
        list(document.acl_principals or []),
        list(document.tags or []),
        document.author,
        document.uri,
        dict(document.metadata_ or {}),
    )
    return before != after


# --- Metadata propagation -------------------------------------------------------------------------------


async def sync_index_metadata(session: AsyncSession, document: Document, source: Source | None) -> None:
    """Propagate classification / ACL / tags / title to the chunks (Postgres now, index now or via a job).

    ACL and classification changes must take effect immediately: the index is updated synchronously;
    if OpenSearch is unavailable a ``reindex`` job (``mode=metadata``) is queued as a fallback.
    """
    await session.execute(
        update(Chunk)
        .where(Chunk.document_id == document.id, Chunk.status != ChunkStatus.forgotten)
        .values(classification=int(document.classification), acl_principals=list(document.acl_principals))
    )
    fields = document_index_fields(document, source)
    try:
        await opensearch.update_by_query(
            "chunks", {"term": {"document_id": str(document.id)}}, fields, refresh=True
        )
    except Exception as exc:  # index unavailable: the worker will retry the propagation
        logger.warning(
            "Index metadata update failed for document %s: %s — reindex job queued", document.id, exc
        )
        await enqueue_job(
            session, document.project_id, JobKind.reindex, document.id, payload={"mode": "metadata"}
        )


__all__ = [
    "DEFAULT_SOURCE_NAMES",
    "ContentIn",
    "DocumentViewer",
    "IngestOutcome",
    "clean_metadata",
    "default_source",
    "get_project_source",
    "get_visible_document",
    "ingest_content",
    "parse_acl_field",
    "parse_tags_csv",
    "resolve_source",
    "serialize_summaries",
    "serialize_summary",
    "sync_index_metadata",
    "title_from_filename",
]
