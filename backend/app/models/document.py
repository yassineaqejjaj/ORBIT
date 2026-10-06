"""Documents, their immutable versions and the chunks indexed for retrieval."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, Text
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin, utcnow
from app.enums import ChunkStatus, DocumentStatus
from app.models._types import StrEnumType, enum_check, range_check
from app.models.source import default_acl


class Document(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        enum_check("status", DocumentStatus),
        range_check("classification", 0, 3),
        Index(
            "uq_documents_project_id_source_id_external_id",
            "project_id",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=sql_text("external_id IS NOT NULL"),
        ),
        Index("ix_documents_project_id_status", "project_id", "status"),
        Index("ix_documents_source_id", "source_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="text/plain", server_default=sql_text("'text/plain'")
    )
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default=sql_text("1")
    )
    acl_principals: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=default_acl,
        server_default=sql_text("ARRAY['project:*']::text[]"),
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=sql_text("'{}'::text[]")
    )
    # ``metadata`` is reserved by SQLAlchemy's declarative API: attribute ``metadata_``, column "metadata".
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )
    status: Mapped[DocumentStatus] = mapped_column(
        StrEnumType(DocumentStatus),
        nullable=False,
        default=DocumentStatus.pending,
        server_default=sql_text("'pending'"),
    )
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=sql_text("1")
    )
    pii_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sql_text("0"))
    #: Business date of the content (freshness policies). Defaults to ingestion time.
    source_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=sql_text("now()")
    )
    forgotten_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forgotten_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DocumentVersion(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        Index("uq_document_versions_document_id_version", "document_id", "version", unique=True),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=sql_text("0")
    )
    extracted_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=sql_text("''")
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=sql_text("'{}'::jsonb")
    )


class Chunk(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        enum_check("status", ChunkStatus),
        range_check("classification", 0, 3),
        Index("ix_chunks_document_id_version", "document_id", "version"),
        Index("ix_chunks_project_id_status", "project_id", "status"),
        Index("ix_chunks_project_id_quarantined", "project_id", postgresql_where=sql_text("quarantined")),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sql_text("0"))
    section: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sql_text("0"))
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sql_text("0"))
    #: ``[{"type": "EMAIL", "start": 12, "end": 30, "text": "..."}]`` (offsets in ``text``).
    pii: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    classification: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default=sql_text("1")
    )
    acl_principals: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=default_acl,
        server_default=sql_text("ARRAY['project:*']::text[]"),
    )
    status: Mapped[ChunkStatus] = mapped_column(
        StrEnumType(ChunkStatus),
        nullable=False,
        default=ChunkStatus.active,
        server_default=sql_text("'active'"),
    )
    # --- Prompt-injection quarantine (docs/AI_CONTEXT_ENGINEERING.md §A1) ---
    injection_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default=sql_text("0")
    )
    #: ``[{"code": "IGNORE_INSTRUCTIONS", "label": "...", "weight": 0.7, "excerpt": "..."}]``.
    injection_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    quarantined: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sql_text("false")
    )
    quarantine_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_released_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
