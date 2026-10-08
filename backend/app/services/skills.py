"""Procedural memory as skills (docs/AI_CONTEXT_ENGINEERING.md §D1): visible procedures of a project.

Shared by the REST router (``/projects/{slug}/skills``), the MCP tools ``list_skills`` / ``get_skill`` and
the context assembler. Visibility is the memory visibility (ACL, clearance, private user memory).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import MemoryKind, MemoryStatus
from app.memory import skills
from app.memory.visibility import MemoryViewer, visibility_clause
from app.models import MemoryItem

ACTIVE = (MemoryStatus.validated, MemoryStatus.proposed)
LIST_LIMIT = 200


async def list_procedures(
    session: AsyncSession, viewer: MemoryViewer, *, validated_only: bool = False
) -> list[MemoryItem]:
    """Current procedures visible to ``viewer`` (validated first, then most recent)."""
    statuses = (MemoryStatus.validated,) if validated_only else ACTIVE
    rows = await session.scalars(
        select(MemoryItem)
        .where(
            visibility_clause(viewer),
            MemoryItem.is_current.is_(True),
            MemoryItem.kind == MemoryKind.procedure,
            MemoryItem.status.in_(statuses),
        )
        .order_by(MemoryItem.updated_at.desc())
        .limit(LIST_LIMIT)
    )
    items = list(rows)
    items.sort(key=lambda i: MemoryStatus(i.status) != MemoryStatus.validated)
    return items


async def find_skill(session: AsyncSession, viewer: MemoryViewer, name: str) -> MemoryItem | None:
    """Procedure whose skill name (or memory/lineage id) is ``name``; validated versions win."""
    wanted = name.strip().lower()
    for item in await list_procedures(session, viewer):
        if wanted in (skills.meta_of(item)["name"], str(item.id), str(item.lineage_id)):
            return item
    return None


def summary(item: MemoryItem) -> dict[str, Any]:
    meta = skills.meta_of(item)
    return {
        **meta,
        "title": item.title,
        "memory_id": item.id,
        "lineage_id": item.lineage_id,
        "version": item.version,
        "status": MemoryStatus(item.status).value,
        "classification": int(item.classification),
        "updated_at": item.updated_at,
    }


__all__ = ["find_skill", "list_procedures", "summary"]
