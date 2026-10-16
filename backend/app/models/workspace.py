"""Workspaces (ADR 001 §5): the isolation boundary of one organisation (NOV-106).

``workspaces.id`` **is** ``orion_workspace_id``. Users, projects, agent keys and webhooks carry a
``workspace_id`` (NOT NULL, defaulting to the default workspace created by the migration, immutable once
stored). Every other project resource (documents, chunks, memory, snapshots, context requests, search
indices) inherits its workspace **through its project**: the search indices are therefore not reindexed.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Text, event, inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.config import settings
from app.db import Base, CreatedAtMixin, UUIDPkMixin


def default_workspace_id() -> uuid.UUID:
    """Python-side default of every ``workspace_id`` column (the migration sets the same SQL default)."""
    return settings.default_workspace_id


class Workspace(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(Text, nullable=False)


def workspace_id_column() -> Mapped[uuid.UUID]:
    """``workspace_id`` NOT NULL, defaulting to the default workspace (shared by the four owning tables)."""
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        default=default_workspace_id,
    )


def _forbid_workspace_change(_mapper: Mapper[Any], _connection: Any, target: Any) -> None:
    """ADR §9 invariant 1: the workspace of a stored row never changes."""
    history = inspect(target).attrs.workspace_id.history
    if history.has_changes() and history.deleted:
        raise ValueError("workspace_id est immuable une fois la ligne créée")


def forbid_workspace_change(*models: type) -> None:
    for model in models:
        event.listen(model, "before_update", _forbid_workspace_change)
