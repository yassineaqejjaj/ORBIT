"""Audit trail writer & reader (ARCHITECTURE §12).

``record()`` only adds the row to the session: it is committed with the caller's transaction, so an
action and its audit entry succeed or fail together.

Convention for ``details``: anything that must not be shown to non-owners (excluded item titles,
ACL principals…) goes under ``details["restricted"]`` — it is stripped for viewers/editors.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ActorType
from app.models import Agent, AuditLog, User

SYSTEM_LABEL = "Système ORBIT"
RESTRICTED_KEY = "restricted"


class AuditAction(StrEnum):
    """Standard action names (``<domain>.<verb>``). Filtering by ``domain`` matches every verb."""

    auth_login = "auth.login"
    auth_login_failed = "auth.login_failed"
    auth_logout = "auth.logout"
    user_create = "user.create"
    user_update = "user.update"
    project_create = "project.create"
    project_update = "project.update"
    member_add = "member.add"
    member_update = "member.update"
    member_remove = "member.remove"
    agent_create = "agent.create"
    agent_rotate = "agent.rotate"
    agent_revoke = "agent.revoke"
    source_create = "source.create"
    source_update = "source.update"
    document_ingest = "document.ingest"
    document_import = "document.import"
    document_update = "document.update"
    document_reprocess = "document.reprocess"
    document_forget = "document.forget"
    document_indexed = "document.indexed"
    document_failed = "document.failed"
    memory_create = "memory.create"
    memory_edit = "memory.edit"
    memory_validate = "memory.validate"
    memory_obsolete = "memory.obsolete"
    memory_supersede = "memory.supersede"
    memory_restore = "memory.restore"
    memory_forget = "memory.forget"
    memory_conflict = "memory.conflict"
    memory_consolidate = "memory.consolidate"
    memory_bulk = "memory.bulk"
    memory_conflict_resolved = "memory.conflict_resolved"
    memory_conflict_dismissed = "memory.conflict_dismissed"
    memory_reflection = "memory.reflection"
    entity_create = "entity.create"
    entity_merge = "entity.merge"
    entity_unmerge = "entity.unmerge"
    document_stale = "document.stale"
    subscription_update = "subscription.update"
    webhook_create = "webhook.create"
    webhook_update = "webhook.update"
    webhook_delete = "webhook.delete"
    webhook_test = "webhook.test"
    webhook_disabled = "webhook.disabled"
    session_close = "session.close"
    context_request = "context.request"
    context_feedback = "context.feedback"
    context_expand = "context.expand"
    snapshot_create = "snapshot.create"
    acl_change = "governance.acl_change"
    classification_change = "governance.classification_change"
    traces_export = "traces.export"
    chunk_quarantine = "security.quarantine"
    quarantine_release = "security.quarantine_release"
    poisoning_alert = "security.poisoning_alert"
    compliance_export = "compliance.export"
    #: Chantier E (docs/AI_CONTEXT_ENGINEERING.md §E).
    eval_set_change = "evaluation.set_change"
    eval_run = "evaluation.run"
    ranking_weights_change = "evaluation.ranking_weights"
    judge_export = "evaluation.judge_export"
    a2a_handoff_issue = "a2a.handoff_issue"
    a2a_handoff_receive = "a2a.handoff_receive"
    a2a_handoff_reject = "a2a.handoff_reject"


@dataclass(frozen=True, slots=True)
class Actor:
    type: ActorType
    id: uuid.UUID | None
    label: str

    @classmethod
    def system(cls, label: str = SYSTEM_LABEL) -> Actor:
        return cls(ActorType.system, None, label)

    @classmethod
    def from_user(cls, user: User) -> Actor:
        return cls(ActorType.user, user.id, user.full_name or user.email)

    @classmethod
    def from_agent(cls, agent: Agent) -> Actor:
        return cls(ActorType.agent, agent.id, agent.name)


class _HasActor(Protocol):
    @property
    def actor(self) -> Actor: ...


ActorLike = Actor | User | Agent | _HasActor | None


def resolve_actor(actor: ActorLike) -> Actor:
    """Accept an :class:`Actor`, a ``Principal`` (``.actor``), a ``User``, an ``Agent`` or ``None``."""
    if actor is None:
        return Actor.system()
    if isinstance(actor, Actor):
        return actor
    if isinstance(actor, User):
        return Actor.from_user(actor)
    if isinstance(actor, Agent):
        return Actor.from_agent(actor)
    resolved = getattr(actor, "actor", None)
    if isinstance(resolved, Actor):
        return resolved
    raise TypeError(f"Unsupported audit actor: {type(actor).__name__}")


async def record(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    actor: ActorLike,
    action: str,
    target_type: str = "",
    target_id: uuid.UUID | str | None = None,
    summary: str = "",
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry to the current transaction (the caller commits)."""
    resolved = resolve_actor(actor)
    entry = AuditLog(
        project_id=project_id,
        actor_type=resolved.type,
        actor_id=resolved.id,
        actor_label=resolved.label,
        action=str(action),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        summary=summary,
        details=_jsonable(details or {}),
    )
    session.add(entry)
    if project_id is not None:
        # Change feed (docs/FEATURES.md F2): notable actions also produce a change event.
        from app.features.feed.events import on_audit

        await on_audit(
            session, project_id, resolved.label, str(action), target_type, target_id, summary, details or {}
        )
    return entry


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def visible_details(details: dict[str, Any] | None, *, can_see_restricted: bool) -> dict[str, Any]:
    """Strip ``details["restricted"]`` for callers that are not owners/admins."""
    data = dict(details or {})
    if not can_see_restricted:
        data.pop(RESTRICTED_KEY, None)
    return data


async def list_events(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    action: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[AuditLog], int]:
    """Project audit entries, newest first. ``action`` matches exactly or as a ``<domain>`` prefix."""
    conditions = [AuditLog.project_id == project_id]
    if action:
        action = action.strip().removesuffix(".*")
        conditions.append(or_(AuditLog.action == action, AuditLog.action.startswith(f"{action}.")))
    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
    rows = await session.scalars(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)
