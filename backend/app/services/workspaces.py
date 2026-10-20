"""Workspace isolation (ADR 001 §9, NOV-106): enforcement mode and the single place that decides.

* ``off`` (default) — nothing is evaluated: historical behaviour, byte for byte.
* ``shadow`` — the filter is evaluated, a violation increments ``orbit_workspace_violations_total`` and is
  logged (ids only), the request is served as before.
* ``enforce`` — a resource of another workspace answers like an unknown one (404, same message).

The workspace of a request comes **only** from the validated identity (the user's or agent's own
``workspace_id``), never from a parameter, a header or a body. Project resources (documents, chunks, memory,
snapshots, context requests, search indices) inherit their workspace through their project: the project is
the filter, so no index is rewritten.
"""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.observability.metrics import record_workspace_violation

logger = logging.getLogger("orbit.workspace")


class Mode(StrEnum):
    off = "off"
    shadow = "shadow"
    enforce = "enforce"


class _HasWorkspace(Protocol):
    workspace_id: uuid.UUID


def mode() -> Mode:
    """Current mode (read on each call so a restart-free test or reload of settings is honoured)."""
    return Mode(settings.workspace_enforcement)


def is_enforcing() -> bool:
    return mode() is Mode.enforce


def allows(subject_workspace_id: uuid.UUID, resource_workspace_id: uuid.UUID, *, surface: str) -> bool:
    """``True`` when the access may proceed.

    ``off`` never compares. A mismatch is counted in ``shadow`` and ``enforce``; only ``enforce`` refuses.
    """
    current = mode()
    if current is Mode.off or subject_workspace_id == resource_workspace_id:
        return True
    record_workspace_violation(mode=current.value, surface=surface)
    logger.warning(
        "workspace violation (%s) on %s: subject=%s resource=%s",
        current.value,
        surface,
        subject_workspace_id,
        resource_workspace_id,
    )
    return current is Mode.shadow


def org_memory_visible(project: _HasWorkspace | None) -> bool:
    """Organisation-wide memory (``project_id IS NULL``) has no project to inherit a workspace from.

    It belongs to the **default workspace** (that is where every pre-existing row lives). Under ``enforce`` it
    is served only to the projects of the default workspace; ``off`` and ``shadow`` keep serving it everywhere
    (``shadow`` counts the access that ``enforce`` would refuse).
    """
    current = mode()
    if current is Mode.off or project is None:
        return True
    if project.workspace_id == settings.default_workspace_id:
        return True
    record_workspace_violation(mode=current.value, surface="org_memory")
    return current is Mode.shadow


async def org_memory_visible_for(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """:func:`org_memory_visible` for call sites that only hold the project id (no query when ``off``)."""
    if mode() is Mode.off:
        return True
    from app.models import Project

    workspace_id = await session.scalar(select(Project.workspace_id).where(Project.id == project_id))
    if workspace_id is None:
        return True  # unknown project: nothing to isolate (callers already failed on it)
    return org_memory_visible(_Workspaced(workspace_id))


class _Workspaced:
    __slots__ = ("workspace_id",)

    def __init__(self, workspace_id: uuid.UUID) -> None:
        self.workspace_id = workspace_id
