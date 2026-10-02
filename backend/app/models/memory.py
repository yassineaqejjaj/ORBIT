"""Governed memory: append-only versioned items, provenance, history events and the relation graph."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin, utcnow
from app.enums import (
    ActorType,
    MemoryEventType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RelationNodeType,
    RelationType,
)
from app.models._types import StrEnumType, enum_check, range_check
from app.models.source import default_acl


class MemoryItem(UUIDPkMixin, TimestampMixin, Base):
    """One version of a memory item. All versions of an item share ``lineage_id``; one is ``is_current``."""

    __tablename__ = "memory_items"
    __table_args__ = (
        enum_check("scope", MemoryScope),
        enum_check("kind", MemoryKind),
        enum_check("status", MemoryStatus),
        enum_check("created_by_type", ActorType),
        range_check("classification", 0, 3),
        range_check("confidence", 0, 1),
        Index("ix_memory_items_project_id_scope_status", "project_id", "scope", "status"),
        Index("ix_memory_items_lineage_id", "lineage_id"),
        Index("uq_memory_items_lineage_id_version", "lineage_id", "version", unique=True),
        Index("ix_memory_items_subject_user_id", "subject_user_id"),
        Index("ix_memory_items_session_id", "session_id"),
    )

    #: ``NULL`` = organisation-wide long-term memory.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    lineage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    scope: Mapped[MemoryScope] = mapped_column(StrEnumType(MemoryScope), nullable=False)
    kind: Mapped[MemoryKind] = mapped_column(StrEnumType(MemoryKind), nullable=False)
    status: Mapped[MemoryStatus] = mapped_column(
        StrEnumType(MemoryStatus),
        nullable=False,
        default=MemoryStatus.proposed,
        server_default=text("'proposed'"),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(REAL, nullable=False, default=0.7, server_default=text("0.7"))
    classification: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default=text("1")
    )
    acl_principals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=default_acl, server_default=text("ARRAY['project:*']::text[]")
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'::text[]")
    )
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True
    )
    created_by_type: Mapped[ActorType] = mapped_column(
        StrEnumType(ActorType), nullable=False, default=ActorType.system, server_default=text("'system'")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Memory card fields (F3, LLM-assisted extraction — nullable, migration f002).
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class MemoryProvenance(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "memory_provenance"
    __table_args__ = (
        Index("ix_memory_provenance_memory_item_id", "memory_item_id"),
        Index("ix_memory_provenance_document_id", "document_id"),
        Index("ix_memory_provenance_chunk_id", "chunk_id"),
    )

    memory_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )
    context_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_requests.id", ondelete="SET NULL"), nullable=True
    )
    source_label: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))


class MemoryEvent(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "memory_events"
    __table_args__ = (
        enum_check("event", MemoryEventType),
        enum_check("actor_type", ActorType),
        Index("ix_memory_events_lineage_id_created_at", "lineage_id", "created_at"),
        Index("ix_memory_events_memory_item_id", "memory_item_id"),
    )

    memory_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="CASCADE"), nullable=False
    )
    lineage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event: Mapped[MemoryEventType] = mapped_column(StrEnumType(MemoryEventType), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(StrEnumType(ActorType), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class Relation(UUIDPkMixin, CreatedAtMixin, Base):
    """Typed edge between chunks, memory items and documents (memory graph, supersession, conflicts)."""

    __tablename__ = "relations"
    __table_args__ = (
        enum_check("src_type", RelationNodeType),
        enum_check("dst_type", RelationNodeType),
        enum_check("rel_type", RelationType),
        range_check("confidence", 0, 1),
        Index("uq_relations_src_id_rel_type_dst_id", "src_id", "rel_type", "dst_id", unique=True),
        Index("ix_relations_dst_id", "dst_id"),
        Index("ix_relations_project_id_rel_type", "project_id", "rel_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    src_type: Mapped[RelationNodeType] = mapped_column(StrEnumType(RelationNodeType), nullable=False)
    src_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rel_type: Mapped[RelationType] = mapped_column(StrEnumType(RelationType), nullable=False)
    dst_type: Mapped[RelationNodeType] = mapped_column(StrEnumType(RelationNodeType), nullable=False)
    dst_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    confidence: Mapped[float] = mapped_column(REAL, nullable=False, default=1.0, server_default=text("1"))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
