"""Sources, documents, versions, chunks, ingestion jobs and search hits."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, Field

from app.enums import ChunkStatus, DocumentStatus, JobKind, JobStatus, PiiType, SourceKind, SourceTrust
from app.schemas.common import AclPrincipals, ApiModel, ClassificationLevel, InputModel, Tags
from app.schemas.memory import MemoryItem

# --- Sources --------------------------------------------------------------------------------------


class SourceCounts(ApiModel):
    documents: int = 0
    indexed: int = 0
    failed: int = 0
    processing: int = 0


class Source(ApiModel):
    id: uuid.UUID
    name: str
    kind: SourceKind
    description: str
    default_classification: int
    default_acl: list[str]
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_ingested_at: datetime | None
    #: Explicit trust (``None`` = default of the kind) and the effective level (§A3).
    trust: SourceTrust | None = None
    effective_trust: SourceTrust = SourceTrust.medium
    counts: SourceCounts = Field(default_factory=SourceCounts)


class SourceCreateIn(InputModel):
    name: str = Field(min_length=1, max_length=200)
    kind: SourceKind
    description: str = Field(default="", max_length=2000)
    default_classification: ClassificationLevel = 1
    default_acl: AclPrincipals = Field(default_factory=lambda: ["project:*"])
    config: dict[str, Any] = Field(default_factory=dict)
    trust: SourceTrust | None = None


class SourceUpdateIn(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: SourceKind | None = None
    description: str | None = Field(default=None, max_length=2000)
    default_classification: ClassificationLevel | None = None
    default_acl: AclPrincipals | None = None
    config: dict[str, Any] | None = None
    #: Owners only (raising the trust of a source is a security decision).
    trust: SourceTrust | None = None


# --- Documents ------------------------------------------------------------------------------------


class PiiEntity(ApiModel):
    type: PiiType
    start: int
    end: int
    text: str | None = Field(default=None, description="Omis si l'appelant n'est pas au moins éditeur")


class ChunkView(ApiModel):
    id: uuid.UUID
    version: int
    ordinal: int
    text: str
    text_redacted: str
    token_count: int
    section: str | None
    pii: list[PiiEntity]
    classification: int
    status: ChunkStatus
    #: Prompt-injection scan (docs/AI_CONTEXT_ENGINEERING.md §A1).
    injection_score: float = 0.0
    injection_reasons: list[dict[str, Any]] = []
    quarantined: bool = False
    quarantine_released_at: datetime | None = None
    #: Contextual-retrieval preamble indexed with the chunk (§B1) and its origin (llm / deterministic).
    context_preamble: str | None = None
    context_source: str | None = None


class QuarantinedChunk(ApiModel):
    """A chunk held in quarantine (never served) — owners can review and release it."""

    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    version: int
    ordinal: int
    section: str | None
    text: str
    injection_score: float
    injection_reasons: list[dict[str, Any]]
    created_at: datetime


class DocumentVersion(ApiModel):
    id: uuid.UUID
    version: int
    content_hash: str
    size_bytes: int
    created_at: datetime
    char_count: int = 0


class JobStep(ApiModel):
    name: str = Field(description="extract | pii | classify | chunk | embed | index | extract_memory | …")
    status: Literal["ok", "failed", "skipped"]
    duration_ms: float = 0
    detail: str | None = None
    started_at: datetime | None = None


class Job(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID | None
    kind: JobKind
    status: JobStatus
    attempts: int
    error: str | None
    steps: list[JobStep]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobWithDocument(Job):
    document_title: str | None = None


class DocumentSummary(ApiModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_name: str = ""
    source_kind: SourceKind | None = None
    external_id: str | None
    title: str
    uri: str | None
    mime_type: str
    author: str | None
    classification: int
    acl_principals: list[str]
    tags: list[str]
    status: DocumentStatus
    status_reason: str | None
    current_version: int
    pii_count: int
    chunk_count: int = 0
    source_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    metadata: dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("metadata_", "metadata")
    )
    versions: list[DocumentVersion] = Field(default_factory=list)
    chunks: list[ChunkView] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)
    memory_items: list[MemoryItem] = Field(default_factory=list)
    forgotten_at: datetime | None = None
    forgotten_by: uuid.UUID | None = None


class TextDocumentIn(InputModel):
    source_id: uuid.UUID | None = None
    source_kind: SourceKind | None = None
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=5_000_000)
    external_id: str | None = Field(default=None, max_length=300)
    uri: str | None = Field(default=None, max_length=2000)
    author: str | None = Field(default=None, max_length=300)
    classification: ClassificationLevel | None = None
    acl_principals: AclPrincipals | None = None
    tags: Tags | None = None
    source_updated_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class DocumentUpdateIn(InputModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    classification: ClassificationLevel | None = None
    acl_principals: AclPrincipals | None = None
    tags: Tags | None = None


class ForgetIn(InputModel):
    reason: str = Field(min_length=1, max_length=2000)


class ImportResult(ApiModel):
    created: int
    updated: int
    documents: list[DocumentSummary]


# --- Search ---------------------------------------------------------------------------------------


class SearchHit(ApiModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    source_kind: SourceKind | None
    text: str
    score: float
    bm25: float | None = None
    dense: float | None = None
    section: str | None = None
    source_updated_at: datetime | None = None
