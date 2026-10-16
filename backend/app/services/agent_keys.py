"""Administration of agent keys (ADR 001 §7, NOV-112).

Inventory without any secret, and the sweep that revokes a key whose workspace is no longer its
project's. A key is attached to **one project and one workspace** (``agents.project_id`` and
``agents.workspace_id``), carries an **explicit clearance and role**, an optional **expiry** and a
**rotation** date. Nothing here reads or prints ``api_key_hash`` or a key: only the public prefix.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import classification_code
from app.models import Agent, Project
from app.security import mask_api_key
from app.services import audit

#: Statuses, most severe first: ``misplaced`` (workspace differs from the project's) beats ``revoked``.
STATUSES = ("misplaced", "revoked", "expired", "active")


@dataclass(frozen=True, slots=True)
class KeyRow:
    key: str  # ``orb_<prefix>…`` — never the secret
    agent_id: uuid.UUID
    name: str
    kind: str
    project: str
    project_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str
    clearance: str
    status: str
    age_days: int
    last_used_days_ago: int | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    rotated_at: datetime | None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for name, value in data.items():
            if isinstance(value, datetime):
                data[name] = value.isoformat()
            elif isinstance(value, uuid.UUID):
                data[name] = str(value)
        return data


def status_of(agent: Agent, project: Project, *, now: datetime) -> str:
    if agent.workspace_id != project.workspace_id:
        return "misplaced"
    if not agent.active:
        return "revoked"
    if agent.expires_at is not None and agent.expires_at <= now:
        return "expired"
    return "active"


def _row(agent: Agent, project: Project, now: datetime) -> KeyRow:
    return KeyRow(
        key=mask_api_key(agent.api_key_prefix),
        agent_id=agent.id,
        name=agent.name,
        kind=str(agent.kind),
        project=project.slug,
        project_id=project.id,
        workspace_id=agent.workspace_id,
        role=agent.role,
        clearance=classification_code(agent.clearance),
        status=status_of(agent, project, now=now),
        age_days=max((now - agent.created_at).days, 0),
        last_used_days_ago=max((now - agent.last_used_at).days, 0) if agent.last_used_at else None,
        created_at=agent.created_at,
        last_used_at=agent.last_used_at,
        expires_at=agent.expires_at,
        rotated_at=agent.rotated_at,
    )


async def inventory(
    session: AsyncSession, *, workspace_id: uuid.UUID | None = None, project_slug: str | None = None
) -> list[KeyRow]:
    """Every key (read only), by workspace then project then age, optionally filtered."""
    query = (
        select(Agent, Project)
        .join(Project, Project.id == Agent.project_id)
        .order_by(Agent.workspace_id, Project.slug, Agent.created_at)
    )
    if workspace_id is not None:
        query = query.where(Agent.workspace_id == workspace_id)
    if project_slug is not None:
        query = query.where(Project.slug == project_slug)
    now = utcnow()
    return [_row(agent, project, now) for agent, project in (await session.execute(query)).tuples()]


async def revoke_misplaced(session: AsyncSession, *, dry_run: bool) -> list[KeyRow]:
    """Revoke the active keys whose workspace differs from their project's ("a key that left the workspace").

    Returns the affected keys (as they were). With ``dry_run`` nothing is written; otherwise the keys are
    deactivated and one audit entry per key is recorded (system actor, no secret).
    """
    now = utcnow()
    query = (
        select(Agent, Project)
        .join(Project, Project.id == Agent.project_id)
        .where(Agent.workspace_id != Project.workspace_id, Agent.active.is_(True))
        .order_by(Project.slug, Agent.created_at)
    )
    found = list((await session.execute(query)).tuples())
    rows = [_row(agent, project, now) for agent, project in found]
    if dry_run:
        return rows
    for agent, project in found:
        agent.active = False
        await audit.record(
            session,
            project.id,
            audit.Actor.system(),
            audit.AuditAction.agent_revoke,
            "agent",
            agent.id,
            summary=f"Révocation de la clé de l'agent « {agent.name} » (hors de l'espace de son projet)",
            details={
                "reason": "left_workspace",
                "api_key_prefix": agent.api_key_prefix,
                "key_workspace_id": str(agent.workspace_id),
                "project_workspace_id": str(project.workspace_id),
            },
        )
    await session.commit()
    return rows
