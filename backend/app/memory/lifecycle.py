"""Memory lifecycle (interface — implemented by the memory teammate). ARCHITECTURE §8.

Rules the implementation must honour:

* **Append-only versioning**: any edit creates a new ``MemoryItem`` row with the same ``lineage_id``
  and ``version + 1``; the previous row gets ``is_current = False``. Every transition writes a
  ``MemoryEvent`` (``created``, ``edited``, ``validated``, ``superseded``, ``obsoleted``,
  ``forgotten``, ``restored``, ``conflict_detected``) and an audit entry (``app.services.audit``).
* **Supersession**: a new decision whose cosine similarity with a ``validated`` decision of the same
  project is > 0.80 and that comes from a more recent source supersedes it (``supersedes_id`` /
  ``superseded_by_id``, old status ``superseded``, relation ``supersedes``); reversible via restore.
* **Contradiction**: similarity > 0.70 with diverging markers (negation, different numbers,
  antonyms) and no clear temporal order ⇒ relation ``contradicts`` + ``conflict_detected`` event.
* **Selective forgetting**: tombstone, removal from the index, status ``forgotten``, content replaced
  by ``[oublié]`` (title/metadata kept for audit), propagation to derived items (all provenances
  forgotten ⇒ forgotten; otherwise confidence reduced), Valkey purge, snapshot items flagged.
* Derived items: ACL = ``app.governance.acl.merge_acls`` of sources, classification = max.
* Agents can only create ``proposed`` items.

All functions flush but do not commit (the caller commits).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import MemoryEventType
from app.models import Document, MemoryEvent, MemoryItem, Relation
from app.schemas.memory import MemoryIn, MemoryUpdateIn
from app.services.audit import ActorLike

FORGOTTEN_CONTENT = "[oublié]"
SUPERSEDE_SIMILARITY = 0.80
CONFLICT_SIMILARITY = 0.70


async def create_item(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None,
    data: MemoryIn,
    actor: ActorLike,
    force_status: str | None = None,
) -> MemoryItem:
    """Create version 1 of a memory item (+ provenance rows, ``created`` event, indexing, relation
    detection). ``force_status="proposed"`` is used for agent callers."""
    raise NotImplementedError("Création d'items mémoire non implémentée")


async def new_version(
    session: AsyncSession,
    item: MemoryItem,
    changes: MemoryUpdateIn | Mapping[str, Any],
    actor: ActorLike,
    *,
    reason: str | None = None,
    event: MemoryEventType = MemoryEventType.edited,
) -> MemoryItem:
    """Append a new version with ``changes`` applied; the previous version becomes non-current."""
    raise NotImplementedError


async def validate(
    session: AsyncSession, item: MemoryItem, actor: ActorLike, reason: str | None = None
) -> MemoryItem:
    raise NotImplementedError


async def obsolete(session: AsyncSession, item: MemoryItem, actor: ActorLike, reason: str) -> MemoryItem:
    raise NotImplementedError


async def supersede(
    session: AsyncSession, old: MemoryItem, new: MemoryItem, actor: ActorLike, reason: str | None = None
) -> MemoryItem:
    """Mark ``old`` as superseded by ``new`` (relation + events). Returns the old item's new version."""
    raise NotImplementedError


async def restore(
    session: AsyncSession, item: MemoryItem, actor: ActorLike, reason: str | None = None
) -> MemoryItem:
    """Undo supersession/obsolescence (back to ``validated`` or ``proposed``)."""
    raise NotImplementedError


async def forget(session: AsyncSession, item: MemoryItem, actor: ActorLike, reason: str) -> MemoryItem:
    """Selective forgetting of a whole lineage (tombstone + propagation, see module docstring)."""
    raise NotImplementedError


async def record_event(
    session: AsyncSession,
    item: MemoryItem,
    event: MemoryEventType,
    actor: ActorLike,
    *,
    reason: str | None = None,
    data: Mapping[str, Any] | None = None,
) -> MemoryEvent:
    raise NotImplementedError


async def detect_relations(session: AsyncSession, item: MemoryItem) -> list[Relation]:
    """Supersession / contradiction detection against current validated items of the project."""
    raise NotImplementedError


async def propagate_document_forget(session: AsyncSession, document: Document, actor: ActorLike) -> int:
    """Forget or down-weight memory items derived from a forgotten document. Returns affected count."""
    raise NotImplementedError


async def run_periodic_maintenance(session: AsyncSession) -> dict[str, int]:
    """Called by the worker every ``ORBIT_WORKER_MAINTENANCE_INTERVAL_SECONDS``: expire short-term
    items, confidence decay of long-term items, consolidation triggers. Returns counters (logged)."""
    raise NotImplementedError
