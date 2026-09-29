"""Seed operations that the REST API does not expose, run through the service layer / database.

The seed normally runs inside the ``api`` container (``make seed``) where the database, OpenSearch and
Valkey are reachable with the default settings. From the host, export ``ORBIT_DATABASE_URL``,
``ORBIT_OPENSEARCH_URL`` and ``ORBIT_VALKEY_URL`` (see the Makefile ``DEV_ENV``). Every function here is
optional for the seed: a failure is reported as a warning and the seed goes on.

* ``reset_demo``          — delete the demo project (cascade), the demo users, their index documents and
                            Valkey sessions, and the organisation memory created by the seed;
* ``ensure_org_memory``   — organisation-level long-term memory (``project_id NULL``), not creatable via
                            the project-scoped API;
* ``expire_session``      — force the expiry of a short-term session (demonstrates ``EXCLUDED_EXPIRED``);
* ``redistribute``        — spread the demo context requests (and their snapshots, feedback and audit
                            rows) over the last 14 days. **Demo data only.**
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class TimestampPlan:
    request_id: uuid.UUID
    created_at: datetime


async def db_available() -> bool:
    from sqlalchemy import text

    from app.db import session_scope

    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


async def project_id_for(slug: str) -> uuid.UUID | None:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models.project import Project

    async with session_scope() as session:
        return (await session.execute(select(Project.id).where(Project.slug == slug))).scalar_one_or_none()


async def reset_demo(slug: str, emails: Sequence[str], org_titles: Sequence[str]) -> dict[str, int]:
    """Delete the demo project and users. Returns counts of what was removed."""
    from sqlalchemy import delete, func, select

    from app.db import session_scope
    from app.models.memory import MemoryItem
    from app.models.project import Project
    from app.models.user import User

    counts = {"projects": 0, "users": 0, "org_memory": 0, "index_docs": 0, "sessions": 0}
    project_id = await project_id_for(slug)
    org_ids: list[str] = []
    async with session_scope() as session:
        if project_id is not None:
            await session.execute(delete(Project).where(Project.id == project_id))
            counts["projects"] = 1
        if org_titles:
            rows = await session.execute(
                select(MemoryItem.id).where(
                    MemoryItem.project_id.is_(None), MemoryItem.title.in_(list(org_titles))
                )
            )
            org_ids = [str(row) for row in rows.scalars()]
            if org_ids:
                await session.execute(
                    delete(MemoryItem).where(MemoryItem.id.in_([uuid.UUID(i) for i in org_ids]))
                )
                counts["org_memory"] = len(org_ids)
    async with session_scope() as session:
        lowered = [email.lower() for email in emails]
        existing = await session.execute(
            select(func.count()).select_from(User).where(User.email.in_(lowered))
        )
        counts["users"] = int(existing.scalar_one())
        await session.execute(delete(User).where(User.email.in_(lowered)))

    if project_id is not None or org_ids:
        from app.search import opensearch

        if project_id is not None:
            for kind in ("chunks", "memory"):
                counts["index_docs"] += await opensearch.delete_by_query(
                    kind, {"term": {"project_id": str(project_id)}}, refresh=True
                )
        if org_ids:
            counts["index_docs"] += await opensearch.delete_by_ids("memory", org_ids, refresh=True)
    if project_id is not None:
        from app.memory.short_term import get_valkey, session_key, sessions_index_key

        client = get_valkey()
        keys = [key async for key in client.scan_iter(match=session_key(project_id, "*"))]
        keys.append(sessions_index_key(project_id))
        counts["sessions"] = int(await client.delete(*keys))
    return counts


async def ensure_org_memory(items: Iterable[dict[str, Any]], admin_email: str) -> tuple[int, int]:
    """Create the organisation long-term memory items that do not exist yet. Returns ``(created, kept)``."""
    from sqlalchemy import select

    from app.db import session_scope
    from app.memory.lifecycle import create_item
    from app.models.memory import MemoryItem
    from app.models.user import User
    from app.schemas.memory import MemoryIn
    from app.services.audit import Actor

    created = kept = 0
    async with session_scope() as session:
        admin = (
            await session.execute(select(User).where(User.email == admin_email.lower()))
        ).scalar_one_or_none()
        actor = Actor.from_user(admin) if admin is not None else Actor.system()
        for item in items:
            exists = await session.execute(
                select(MemoryItem.id).where(
                    MemoryItem.project_id.is_(None),
                    MemoryItem.title == item["title"],
                    MemoryItem.is_current.is_(True),
                )
            )
            if exists.first() is not None:
                kept += 1
                continue
            data = MemoryIn(
                scope=item["scope"],
                kind=item["kind"],
                title=item["title"],
                content=item["content"],
                tags=item.get("tags"),
                confidence=item.get("confidence"),
                status=item.get("status", "validated"),
            )
            await create_item(session, project_id=None, data=data, actor=actor)
            created += 1
    return created, kept


async def expire_session(slug: str, session_id: str, *, days_ago: int = 2) -> int:
    """Force a short-term session into the past: Valkey buffer removed, items ``expires_at`` < now."""
    from sqlalchemy import select, update

    from app.db import session_scope
    from app.enums import MemoryScope
    from app.memory.short_term import clear_session
    from app.models.memory import MemoryItem

    project_id = await project_id_for(slug)
    if project_id is None:
        return 0
    expired_at = datetime.now(UTC) - timedelta(days=days_ago)
    async with session_scope() as session:
        ids = list(
            (
                await session.execute(
                    select(MemoryItem.id).where(
                        MemoryItem.project_id == project_id,
                        MemoryItem.session_id == session_id,
                        MemoryItem.scope == MemoryScope.short_term,
                    )
                )
            ).scalars()
        )
        if ids:
            await session.execute(
                update(MemoryItem).where(MemoryItem.id.in_(ids)).values(expires_at=expired_at)
            )
    await clear_session(project_id, session_id)
    if ids:
        from app.search import opensearch

        await opensearch.update_fields(
            "memory", [str(i) for i in ids], {"expires_at": expired_at.isoformat()}, refresh=True
        )
    return len(ids)


async def redistribute(plan: Sequence[TimestampPlan]) -> int:
    """Move context requests (and their snapshots / feedback / audit rows) to the planned timestamps."""
    from sqlalchemy import select, update

    from app.db import session_scope
    from app.models.audit import AuditLog
    from app.models.context import ContextFeedback, ContextRequest, ContextSnapshot

    moved = 0
    async with session_scope() as session:
        for entry in plan:
            result = await session.execute(
                update(ContextRequest)
                .where(ContextRequest.id == entry.request_id)
                .values(created_at=entry.created_at)
            )
            if not result.rowcount:
                continue
            moved += 1
            snapshot_ids = list(
                (
                    await session.execute(
                        select(ContextSnapshot.id).where(ContextSnapshot.request_id == entry.request_id)
                    )
                ).scalars()
            )
            if snapshot_ids:
                await session.execute(
                    update(ContextSnapshot)
                    .where(ContextSnapshot.id.in_(snapshot_ids))
                    .values(created_at=entry.created_at + timedelta(seconds=2))
                )
            await session.execute(
                update(ContextFeedback)
                .where(ContextFeedback.request_id == entry.request_id)
                .values(created_at=entry.created_at + timedelta(minutes=6))
            )
            targets = [str(entry.request_id), *(str(i) for i in snapshot_ids)]
            await session.execute(
                update(AuditLog).where(AuditLog.target_id.in_(targets)).values(created_at=entry.created_at)
            )
    return moved


async def close_resources() -> None:
    """Dispose the engine and close the OpenSearch / Valkey clients opened by the functions above."""
    from app.db import dispose_engine
    from app.memory.short_term import close_valkey
    from app.search.opensearch import close_client

    for closer in (dispose_engine, close_valkey, close_client):
        try:
            await closer()
        except Exception:
            continue
