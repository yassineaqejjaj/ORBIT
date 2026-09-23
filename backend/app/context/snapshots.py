"""Context snapshots (interface — implemented by the context teammate). ARCHITECTURE §10.

Snapshots are immutable and versioned: ``(project_id, name, version)`` is unique and ``version`` is
auto-incremented per name (``parent_id`` = previous version). ``items`` stores ``SnapshotItem`` dicts
whose ``key`` is ``"chunk:<chunk_id>"`` or ``"memory:<lineage_id>"`` so that diffs compare the same
logical item across versions. Forgotten content is flagged (``forgotten: true``) and redacted when
displayed.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextRequest, ContextSnapshot
from app.schemas.context import ContextPackage
from app.schemas.snapshots import SnapshotDiff, SnapshotGroup
from app.services.audit import ActorLike


def item_key(candidate_type: str, item_id: str, lineage_id: str | None = None) -> str:
    """Stable diff key: ``memory:<lineage_id>`` for memory items, ``<type>:<id>`` otherwise."""
    if candidate_type == "memory" and lineage_id:
        return f"memory:{lineage_id}"
    return f"{candidate_type}:{item_id}"


async def create_snapshot(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    name: str,
    request: ContextRequest,
    package: ContextPackage,
    actor: ActorLike,
) -> ContextSnapshot:
    """Persist a new version of snapshot ``name`` from a served package (flush, caller commits)."""
    raise NotImplementedError("Snapshots non implémentés")


async def get_snapshot(
    session: AsyncSession, project_id: uuid.UUID, name: str, version: int | Literal["latest"] | None = None
) -> ContextSnapshot | None:
    """A given version, or the latest when ``version`` is ``None``/``"latest"``."""
    raise NotImplementedError


async def list_groups(session: AsyncSession, project_id: uuid.UUID) -> list[SnapshotGroup]:
    raise NotImplementedError


async def list_versions(session: AsyncSession, project_id: uuid.UUID, name: str) -> list[ContextSnapshot]:
    """All versions of ``name``, newest first."""
    raise NotImplementedError


def diff(old: ContextSnapshot, new: ContextSnapshot) -> SnapshotDiff:
    """Added / removed / unchanged items between two versions (compared by ``key``)."""
    raise NotImplementedError
