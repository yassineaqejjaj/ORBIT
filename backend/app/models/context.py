"""Context requests, per-candidate governance decisions, feedback and immutable snapshots."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.enums import ActorType, CandidateType, ContextRequestStatus, Intent, PrincipalKind, ReasonCode
from app.models._types import StrEnumType, enum_check, range_check


class ContextRequest(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "context_requests"
    __table_args__ = (
        enum_check("requested_by_type", PrincipalKind),
        enum_check("intent", Intent),
        enum_check("status", ContextRequestStatus),
        Index("ix_context_requests_project_id_created_at", "project_id", text("created_at DESC")),
        Index("ix_context_requests_agent_id", "agent_id"),
        Index("ix_context_requests_trace_id", "trace_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    #: ``on_behalf_of`` user.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_type: Mapped[PrincipalKind] = mapped_column(StrEnumType(PrincipalKind), nullable=False)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Intent] = mapped_column(
        StrEnumType(Intent), nullable=False, default=Intent.general, server_default=text("'general'")
    )
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[ContextRequestStatus] = mapped_column(
        StrEnumType(ContextRequestStatus),
        nullable=False,
        default=ContextRequestStatus.succeeded,
        server_default=text("'succeeded'"),
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    timings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    candidates_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    included_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    cost_estimate: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal(0), server_default=text("0")
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("context_snapshots.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    context_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))


class ContextDecision(UUIDPkMixin, Base):
    """Governance decision for one candidate of a context request (included or excluded, with reason)."""

    __tablename__ = "context_decisions"
    __table_args__ = (
        enum_check("candidate_type", CandidateType),
        enum_check("reason_code", ReasonCode),
        range_check("classification", 0, 3),
        Index("ix_context_decisions_request_id", "request_id"),
        Index("ix_context_decisions_document_id", "document_id"),
        Index("ix_context_decisions_memory_item_id", "memory_item_id"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_requests.id", ondelete="CASCADE"), nullable=False
    )
    candidate_type: Mapped[CandidateType] = mapped_column(StrEnumType(CandidateType), nullable=False)
    #: Chunk / memory item id (uuid as text) or a synthetic id for session turns (``<session_id>:<n>``).
    candidate_id: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    memory_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    source_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[ReasonCode] = mapped_column(StrEnumType(ReasonCode), nullable=False)
    reason_detail: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation: Mapped[str | None] = mapped_column(Text, nullable=True)


class ContextFeedback(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "context_feedback"
    __table_args__ = (
        enum_check("actor_type", PrincipalKind),
        range_check("rating", 1, 5),
        Index("ix_context_feedback_request_id", "request_id"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_requests.id", ondelete="CASCADE"), nullable=False
    )
    actor_type: Mapped[PrincipalKind] = mapped_column(StrEnumType(PrincipalKind), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``[{"citation": "S2", "flag": "outdated"}]``
    item_flags: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


class ContextSnapshot(UUIDPkMixin, CreatedAtMixin, Base):
    """Immutable, versioned shared context (``name`` + auto-incremented ``version``)."""

    __tablename__ = "context_snapshots"
    __table_args__ = (
        enum_check("intent", Intent),
        enum_check("created_by_type", ActorType),
        Index("uq_context_snapshots_project_id_name_version", "project_id", "name", "version", unique=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_requests.id", ondelete="SET NULL"), nullable=True
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Intent] = mapped_column(
        StrEnumType(Intent), nullable=False, default=Intent.general, server_default=text("'general'")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``SnapshotItem`` dicts (see docs/API.md) in presentation order.
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_by_type: Mapped[ActorType] = mapped_column(StrEnumType(ActorType), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
