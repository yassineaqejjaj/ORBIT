"""Models of the « Demander à ORBIT » feature (F4, docs/FEATURES.md): conversations, messages, integrations.

Conversations are private to the user (or agent) that asked: nobody else lists or reads them, owners
included. Each assistant message references the governed ``context_requests`` row it was built from, so
👍/👎 feedback lands in ``context_feedback`` and audits stay reconstructible.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin

ASK_CHANNELS = ("web", "teams", "api")
ASK_ROLES = ("user", "assistant")
ASK_MODES = ("llm", "extractive")
ASK_CONFIDENCES = ("high", "medium", "low")
INTEGRATION_KINDS = ("teams",)


def _in(column: str, values: tuple[str, ...], *, nullable: bool = False) -> CheckConstraint:
    expr = f"{column} IN ({', '.join(repr(v) for v in values)})"
    if nullable:
        expr = f"{column} IS NULL OR {expr}"
    return CheckConstraint(expr, name=column)


class AskConversation(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "ask_conversations"
    __table_args__ = (
        _in("channel", ASK_CHANNELS),
        Index("ix_ask_conversations_project_user", "project_id", "user_id", text("updated_at DESC")),
        Index("ix_ask_conversations_project_agent", "project_id", "agent_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="web", server_default=text("'web'"))


class AskMessage(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "ask_messages"
    __table_args__ = (
        _in("role", ASK_ROLES),
        _in("mode", ASK_MODES, nullable=True),
        _in("confidence", ASK_CONFIDENCES, nullable=True),
        CheckConstraint("rating IS NULL OR rating IN (1, 5)", name="rating"),
        Index("ix_ask_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_ask_messages_request_id", "request_id"),
        Index(
            "uq_ask_messages_external_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ask_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    #: Channel message id (Teams activity id, ``teams:<id>``): replay protection.
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Governed context request the answer was built from (assistant messages).
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_requests.id", ondelete="SET NULL"), nullable=True
    )
    mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``ContextItem`` payloads cited by the answer (already filtered for the asker).
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    follow_ups: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    llm_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    #: Last 👍 (5) / 👎 (1) of the asker, mirrored from ``context_feedback``.
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_feedback.id", ondelete="SET NULL"), nullable=True
    )


class Integration(UUIDPkMixin, TimestampMixin, Base):
    """Per-project chat integration (Microsoft Teams outgoing webhook). Secrets are Fernet-encrypted."""

    __tablename__ = "integrations"
    __table_args__ = (
        _in("kind", INTEGRATION_KINDS),
        UniqueConstraint("project_id", "kind", name="uq_integrations_project_kind"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``{"user_mapping": {"<aadObjectId or email>": "<user uuid>"}, "app_url": "..."}``
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


__all__ = ["AskConversation", "AskMessage", "Integration"]
