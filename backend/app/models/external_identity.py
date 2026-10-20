"""External (OIDC) identities linked to local accounts (ADR 001 §8, NOV-109).

One row = "this IdP subject is this ORBIT user", created only by a **confirmed** link (or, when explicitly
enabled, auto-provisioning). The local account, its password, its clearance and its project memberships are
untouched: the identity only proves *who* is calling. ``(issuer, subject)`` is unique; a user has at most one
identity per issuer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.models.workspace import forbid_workspace_change, workspace_id_column


class ExternalIdentity(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        Index("uq_external_identities_issuer_subject", "issuer", "subject", unique=True),
        Index("uq_external_identities_user_id_issuer", "user_id", "issuer", unique=True),
        Index("ix_external_identities_workspace_id", "workspace_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: Workspace of the token at link time (equals the account's workspace; immutable).
    workspace_id: Mapped[uuid.UUID] = workspace_id_column()
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    #: E-mail the IdP vouched for when the link was made (audit only, never used to authenticate).
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``confirmed`` (user confirmed with their local password), ``auto_provision`` or ``admin_approved``
    #: (NOV-113).
    linked_by: Mapped[str] = mapped_column(Text, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


forbid_workspace_change(ExternalIdentity)
