"""ORM → API conversion for memory items and events (docs/API.md « MemoryItem », « MemoryEvent »).

Labels are resolved in bulk: ``created_by_label`` / ``actor_label`` = user full name, agent name or
« Système ». ``provenance_count`` counts the provenance rows of each version.

Other modules (documents detail, sessions, context) should use :func:`serialize_items` instead of
``MemoryItem.model_validate`` so that labels and counts are filled consistently.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ActorType
from app.models import Agent, MemoryEvent, MemoryItem, MemoryProvenance, User
from app.schemas.memory import MemoryEvent as MemoryEventOut
from app.schemas.memory import MemoryItem as MemoryItemOut

SYSTEM_ACTOR_LABEL = "Système"
UNKNOWN_USER_LABEL = "Utilisateur supprimé"
UNKNOWN_AGENT_LABEL = "Agent supprimé"

ActorRef = tuple[ActorType, uuid.UUID | None]


async def actor_labels(session: AsyncSession, refs: Iterable[ActorRef]) -> dict[ActorRef, str]:
    """Display labels for ``(actor_type, actor_id)`` pairs (users, agents, system)."""
    wanted = {(ActorType(kind), actor_id) for kind, actor_id in refs}
    user_ids = {actor_id for kind, actor_id in wanted if kind == ActorType.user and actor_id}
    agent_ids = {actor_id for kind, actor_id in wanted if kind == ActorType.agent and actor_id}
    users: dict[uuid.UUID, str] = {}
    agents: dict[uuid.UUID, str] = {}
    if user_ids:
        rows = await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(user_ids)))
        users = {uid: (name or email) for uid, name, email in rows.tuples()}
    if agent_ids:
        agent_rows = await session.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))
        agents = {aid: name for aid, name in agent_rows.tuples()}
    labels: dict[ActorRef, str] = {}
    for kind, actor_id in wanted:
        if kind == ActorType.user:
            labels[(kind, actor_id)] = (
                users.get(actor_id, UNKNOWN_USER_LABEL) if actor_id else UNKNOWN_USER_LABEL
            )
        elif kind == ActorType.agent:
            labels[(kind, actor_id)] = (
                agents.get(actor_id, UNKNOWN_AGENT_LABEL) if actor_id else UNKNOWN_AGENT_LABEL
            )
        else:
            labels[(kind, actor_id)] = SYSTEM_ACTOR_LABEL
    return labels


async def provenance_counts(session: AsyncSession, item_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
    ids = list(set(item_ids))
    if not ids:
        return {}
    rows = await session.execute(
        select(MemoryProvenance.memory_item_id, func.count())
        .where(MemoryProvenance.memory_item_id.in_(ids))
        .group_by(MemoryProvenance.memory_item_id)
    )
    return {item_id: int(count) for item_id, count in rows.tuples()}


def to_schema(item: MemoryItem, *, label: str = "", provenance_count: int = 0) -> MemoryItemOut:
    out = MemoryItemOut.model_validate(item)
    out.created_by_label = label
    out.provenance_count = provenance_count
    return out


async def serialize_items(session: AsyncSession, items: Sequence[MemoryItem]) -> list[MemoryItemOut]:
    """Serialize items with ``created_by_label`` and ``provenance_count`` (2 queries in total)."""
    if not items:
        return []
    labels = await actor_labels(
        session, ((ActorType(item.created_by_type), item.created_by_id) for item in items)
    )
    counts = await provenance_counts(session, (item.id for item in items))
    return [
        to_schema(
            item,
            label=labels.get((ActorType(item.created_by_type), item.created_by_id), SYSTEM_ACTOR_LABEL),
            provenance_count=counts.get(item.id, 0),
        )
        for item in items
    ]


async def serialize_item(session: AsyncSession, item: MemoryItem) -> MemoryItemOut:
    return (await serialize_items(session, [item]))[0]


async def serialize_events(session: AsyncSession, events: Sequence[MemoryEvent]) -> list[MemoryEventOut]:
    labels = await actor_labels(session, ((ActorType(e.actor_type), e.actor_id) for e in events))
    result: list[MemoryEventOut] = []
    for event in events:
        out = MemoryEventOut.model_validate(event)
        out.actor_label = labels.get((ActorType(event.actor_type), event.actor_id), SYSTEM_ACTOR_LABEL)
        result.append(out)
    return result
