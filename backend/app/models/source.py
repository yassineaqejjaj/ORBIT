"""Business sources (a named origin of documents: repository, ticketing export, CRM, ...)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin
from app.enums import DEFAULT_SOURCE_TRUST, SourceKind, SourceTrust
from app.models._types import StrEnumType, enum_check, range_check

DEFAULT_ACL: tuple[str, ...] = ("project:*",)


def default_acl() -> list[str]:
    return list(DEFAULT_ACL)


class Source(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        enum_check("kind", SourceKind),
        enum_check("trust", SourceTrust),
        range_check("default_classification", 0, 3),
        Index("ix_sources_project_id_kind", "project_id", "kind"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[SourceKind] = mapped_column(StrEnumType(SourceKind), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    default_classification: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default=text("1")
    )
    default_acl: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=default_acl, server_default=text("ARRAY['project:*']::text[]")
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    #: Explicit trust (§A3); ``None`` = default of the kind (see :attr:`effective_trust`).
    trust: Mapped[SourceTrust | None] = mapped_column(StrEnumType(SourceTrust), nullable=True)
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def effective_trust(self) -> SourceTrust:
        return effective_trust(self.kind, self.trust)


def effective_trust(kind: SourceKind | str, trust: SourceTrust | str | None) -> SourceTrust:
    if trust:
        return SourceTrust(trust)
    return DEFAULT_SOURCE_TRUST.get(SourceKind(kind), SourceTrust.medium)
