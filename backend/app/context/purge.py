"""Purge of forgotten content from persisted context (NOV-97).

Forgetting replaces the text of chunks and memory items, but a served context also lives, as text, in
``context_decisions.excerpt``, ``context_requests.context_text`` and ``context_snapshots`` (``content`` and
``items[].excerpt``). Reading already masks forgotten items; this module rewrites them **at rest**, so a
backup restore or a direct database read no longer returns the text.

Rewritten: excerpts of decisions, the bullet and source lines of the request Markdown and of the snapshot
Markdown (same replacement as at read time), snapshot items (``excerpt`` and ``title`` replaced,
``forgotten`` set) and ``content_hash`` (recomputed). Titles of decisions and the stored cache-prefix hash
of a request are left as they are. The function is idempotent: what is already rewritten is not touched or
counted again.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.snapshots import content_hash
from app.context.visibility import FORGOTTEN_TEXT, redact_markdown
from app.enums import CandidateType
from app.models import ContextDecision, ContextRequest, ContextSnapshot, MemoryItem

logger = logging.getLogger("orbit.context.purge")


@dataclass(slots=True)
class PurgeResult:
    decisions: int = 0
    requests: int = 0
    snapshots: int = 0

    def __bool__(self) -> bool:
        return bool(self.decisions or self.requests or self.snapshots)

    def as_dict(self) -> dict[str, int]:
        return {"decisions": self.decisions, "requests": self.requests, "snapshots": self.snapshots}


#: Ids per ``IN`` list (stays under the driver's bind-parameter limit).
BATCH = 5000


def _batches[T](values: list[T]) -> Iterable[list[T]]:
    for start in range(0, len(values), BATCH):
        yield values[start : start + BATCH]


async def _decisions(
    session: AsyncSession, project_id: uuid.UUID | None, target: Any
) -> list[tuple[uuid.UUID, uuid.UUID, str | None]]:
    """``(id, request_id, citation)`` of the decisions matching ``target`` that still hold their excerpt."""
    stmt = select(ContextDecision.id, ContextDecision.request_id, ContextDecision.citation).where(
        ContextDecision.excerpt != FORGOTTEN_TEXT, target
    )
    if project_id is not None:
        stmt = stmt.join(ContextRequest, ContextRequest.id == ContextDecision.request_id).where(
            ContextRequest.project_id == project_id
        )
    return [tuple(row) for row in (await session.execute(stmt)).tuples().all()]  # type: ignore[misc]


async def purge_persisted_context(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    *,
    chunk_ids: Iterable[uuid.UUID] = (),
    lineage_ids: Iterable[uuid.UUID] = (),
    dry_run: bool = False,
) -> PurgeResult:
    """Rewrite persisted context rows quoting the given chunks / memory lineages (flush, caller commits).

    ``project_id`` is ``None`` for organisation-wide memory, which may have been served in any project.
    With ``dry_run`` nothing is written and the result counts what would be rewritten.
    """
    chunks = {str(c) for c in chunk_ids}
    lineages = {uuid.UUID(str(lineage)) for lineage in lineage_ids}
    result = PurgeResult()
    if not chunks and not lineages:
        return result
    memory_ids: set[uuid.UUID] = set()
    if lineages:
        memory_ids = set(
            await session.scalars(select(MemoryItem.id).where(MemoryItem.lineage_id.in_(lineages)))
        )

    rows: list[tuple[uuid.UUID, uuid.UUID, str | None]] = []
    for batch in _batches(sorted(chunks)):
        rows += await _decisions(
            session,
            project_id,
            and_(
                ContextDecision.candidate_type == CandidateType.chunk, ContextDecision.candidate_id.in_(batch)
            ),
        )
    for memory_batch in _batches(sorted(memory_ids)):
        rows += await _decisions(
            session,
            project_id,
            and_(
                ContextDecision.candidate_type == CandidateType.memory,
                or_(
                    ContextDecision.memory_item_id.in_(memory_batch),
                    ContextDecision.candidate_id.in_([str(m) for m in memory_batch]),
                ),
            ),
        )
    result.decisions = len(rows)
    by_request: dict[uuid.UUID, dict[str, str]] = {}
    for _decision_id, request_id, citation in rows:
        if citation:
            by_request.setdefault(request_id, {})[citation] = FORGOTTEN_TEXT
    if rows and not dry_run:
        for id_batch in _batches([row[0] for row in rows]):
            await session.execute(
                update(ContextDecision)
                .where(ContextDecision.id.in_(id_batch))
                .values(excerpt=FORGOTTEN_TEXT)
                .execution_options(synchronize_session=False)
            )

    for request_id, replacements in by_request.items():
        request = await session.get(ContextRequest, request_id)
        if request is None or not request.context_text:
            continue
        redacted = redact_markdown(request.context_text, replacements)
        if redacted != request.context_text:
            result.requests += 1
            if not dry_run:
                request.context_text = redacted

    result.snapshots = await _purge_snapshots(session, project_id, chunks, lineages, dry_run=dry_run)
    if not dry_run:
        await session.flush()
    return result


def _matches(key: str, chunks: set[str], lineages: set[uuid.UUID]) -> bool:
    kind, _, ident = key.partition(":")
    if kind == CandidateType.chunk.value:
        return ident in chunks
    if kind == CandidateType.memory.value:
        try:
            return uuid.UUID(ident) in lineages
        except ValueError:
            return False
    return False


async def _purge_snapshots(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    chunks: set[str],
    lineages: set[uuid.UUID],
    *,
    dry_run: bool,
) -> int:
    stmt = select(ContextSnapshot)
    if project_id is not None:
        stmt = stmt.where(ContextSnapshot.project_id == project_id)
    changed = 0
    for snapshot in (await session.scalars(stmt)).all():
        items: list[dict[str, Any]] = list(snapshot.items or [])
        replacements: dict[str, str] = {}
        rewritten: list[dict[str, Any]] = []
        touched = False
        for item in items:
            if _matches(str(item.get("key", "")), chunks, lineages) and (
                item.get("excerpt") != FORGOTTEN_TEXT or not item.get("forgotten")
            ):
                item = {**item, "excerpt": FORGOTTEN_TEXT, "title": FORGOTTEN_TEXT, "forgotten": True}
                touched = True
            if item.get("forgotten") and item.get("citation"):
                replacements[str(item["citation"])] = FORGOTTEN_TEXT
            rewritten.append(item)
        if not touched:
            continue
        changed += 1
        if dry_run:
            continue
        snapshot.items = rewritten
        snapshot.content = redact_markdown(snapshot.content, replacements)
        snapshot.content_hash = content_hash(snapshot.content)
    return changed
