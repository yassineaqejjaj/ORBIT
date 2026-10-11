"""Gap-driven completion: re-assemble a context around what a consumer reported missing.

A consumer (typically FORGE, after an agent failed for lack of a business rule) names the missing
information. ORBIT re-runs governed retrieval for the original task plus those gaps, starting from the
original snapshot, and saves the result as the next version of that snapshot. Nothing is overwritten: the
original request and snapshot version stay as they were served, the new request links back to them
(``params.completes_request_id``), and the caller's own access still decides what may be served.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import persistence
from app.context.assembler import assemble_context
from app.deps import ProjectAccess
from app.enums import ReasonCode
from app.errors import not_found
from app.models import ContextDecision, ContextRequest, ContextSnapshot
from app.schemas.context import (
    BaseSnapshotRef,
    CompletedItem,
    ContextCompleteIn,
    ContextCompletion,
    ContextRequestIn,
    SaveSnapshotRef,
)

#: Fields of the original request that carry over (identity and snapshots do not: the caller's apply).
CARRIED = (
    "intent",
    "scopes",
    "source_kinds",
    "freshness_days",
    "max_classification",
    "min_relevance",
    "token_budget",
)


def _rebuild(
    original: ContextRequest, body: ContextCompleteIn, base: ContextSnapshot | None, save_name: str
) -> ContextRequestIn:
    stored: dict[str, Any] = (original.params or {}).get("request") or {}
    carried = {k: stored[k] for k in CARRIED if stored.get(k) is not None}
    carried.setdefault("intent", original.intent.value)
    if body.token_budget:
        carried["token_budget"] = body.token_budget
    gaps = "; ".join(body.missing)
    task = f"{original.task}\n\nMissing information to find: {gaps}"[:8000]
    fields: dict[str, Any] = {
        **carried,
        "task": task,
        "base_snapshot": BaseSnapshotRef(name=base.name, version=base.version) if base else None,
        "save_snapshot": SaveSnapshotRef(name=save_name),
    }
    try:
        return ContextRequestIn(**fields)
    except (
        ValidationError
    ):  # an old request whose stored options no longer validate: complete it with the essentials
        return ContextRequestIn(
            task=task, base_snapshot=fields["base_snapshot"], save_snapshot=fields["save_snapshot"]
        )


async def complete_request(
    session: AsyncSession, access: ProjectAccess, request_id: uuid.UUID, body: ContextCompleteIn
) -> ContextCompletion:
    original = await persistence.get_request(session, access.project_id, request_id)
    principal = access.principal
    if principal.is_agent and principal.id not in (original.agent_id, original.requested_by_id):
        # Same answer as an unknown id: an agent may only complete a context it was served.
        raise not_found("Requête de contexte introuvable")
    base = await session.get(ContextSnapshot, original.snapshot_id) if original.snapshot_id else None
    save_name = body.snapshot.name if body.snapshot else (base.name if base else f"gap-{original.id.hex[:8]}")
    served_before = set(
        await session.scalars(
            select(ContextDecision.candidate_id).where(
                ContextDecision.request_id == original.id, ContextDecision.included.is_(True)
            )
        )
    )

    package = await assemble_context(session, access, _rebuild(original, body, base, save_name))

    row = await session.get(ContextRequest, package.request_id)
    if row is not None:  # link the new request to the one it completes
        row.params = {**(row.params or {}), "completes_request_id": str(original.id), "missing": body.missing}
        await session.commit()
    added = [
        CompletedItem(
            citation=i.citation,
            id=i.id,
            title=i.title,
            source_kind=i.source_kind,
            memory_kind=i.memory_kind,
            classification=i.classification,
        )
        for i in package.items
        if i.id not in served_before and i.reason_code != ReasonCode.INCLUDED_PINNED
    ]
    return ContextCompletion(
        request_id=package.request_id,
        completes=original.id,
        snapshot=package.snapshot,
        added=added,
        still_missing=list(package.sufficiency.missing_subtopics) if package.sufficiency else [],
        sufficiency=package.sufficiency,
        tokens_used=package.tokens_used,
    )
