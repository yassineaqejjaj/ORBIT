"""Projects and project memberships."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Text, event, inspect, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin
from app.enums import Role
from app.models._types import StrEnumType, enum_check
from app.models.workspace import forbid_workspace_change, workspace_id_column


def _default_orion_project_id(context: Any) -> uuid.UUID:
    return context.get_current_parameters()["id"]


class Project(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("uq_projects_slug", "slug", unique=True),
        Index("uq_projects_orion_project_id", "orion_project_id", unique=True),
        Index("ix_projects_workspace_id", "workspace_id"),
    )

    #: Space (ADR 001 §5): the isolation boundary. Immutable.
    workspace_id: Mapped[uuid.UUID] = workspace_id_column()
    #: Project id shared by ORION services (tokens, logs, snapshots). Immutable, globally unique. Equals
    #: ``id`` for every project (the migration backfills it that way, a new project gets its own id unless
    #: it is given one); the slug stays a readable, editable alias.
    orion_project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=_default_orion_project_id
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ProjectMember(CreatedAtMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        enum_check("role", Role),
        Index("ix_project_members_user_id", "user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(StrEnumType(Role), nullable=False)

    def __repr__(self) -> str:
        return f"<ProjectMember project={self.project_id} user={self.user_id} role={self.role}>"


@event.listens_for(Project, "before_update")
def _forbid_orion_project_id_change(_mapper: Any, _connection: Any, target: Project) -> None:
    history = inspect(target).attrs.orion_project_id.history
    if history.has_changes() and history.deleted:
        raise ValueError("orion_project_id est immuable une fois le projet créé")


forbid_workspace_change(Project)
