"""Live hints derived from audited actions (hook in ``services.audit.record``) and job transitions.

Only ids and the classification / ACL used to filter per subscriber: no title, no content. Private
(user, short-term) memory never produces a hint.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import MemoryScope
from app.features.feed.events import PRIVATE_SCOPES, _find
from app.features.live import bus
from app.governance.acl import PROJECT_ALL
from app.models import ContextSnapshot, Document, MemoryItem


async def on_audit(session: AsyncSession, project_id: uuid.UUID, action: str, target_id: Any) -> None:
    if not settings.live_stream:
        return
    try:
        with session.no_autoflush:
            if action.startswith("memory."):
                item = await _find(session, MemoryItem, target_id)
                if item is None or MemoryScope(item.scope) in PRIVATE_SCOPES or item.project_id is None:
                    return
                bus.queue(
                    session,
                    project_id,
                    "memory.changed",
                    {"memory_id": str(item.id)},
                    classification=int(item.classification),
                    acl=list(item.acl_principals or [PROJECT_ALL]),
                )
            elif action.startswith("document."):
                document = await _find(session, Document, target_id)
                bus.queue(
                    session,
                    project_id,
                    "ingestion.updated",
                    {"document_id": str(target_id) if document else None},
                    classification=int(document.classification) if document else 0,
                    acl=list(document.acl_principals or [PROJECT_ALL]) if document else None,
                )
            elif action == "snapshot.create":
                snapshot = await _find(session, ContextSnapshot, target_id)
                bus.queue(
                    session,
                    project_id,
                    "snapshot.created",
                    {"snapshot_id": str(snapshot.id) if snapshot else None},
                )
    except Exception:  # never break the audited action
        return


def job_updated(session: AsyncSession, job: Any) -> None:
    """Queue an ``ingestion.updated`` hint for a job transition (not for webhook deliveries)."""
    if not settings.live_stream or job.project_id is None or str(job.kind) == "webhook":
        return
    payload = job.payload or {}
    bus.queue(
        session,
        job.project_id,
        "ingestion.updated",
        {"job_id": str(job.id), "document_id": payload.get("document_id"), "status": str(job.status)},
    )
