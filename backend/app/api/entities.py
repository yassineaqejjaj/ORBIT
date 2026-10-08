"""Entity resolution (docs/AI_CONTEXT_ENGINEERING.md §D2): entities, aliases, suggested and audited
merges. Suggestions are shown in the Revue mémoire; nothing is merged without a human."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import EditorAccess, SessionDep, ViewerAccess
from app.errors import not_found
from app.memory import entities as entity_service
from app.models import Entity
from app.schemas.memory import EntityAliasOut, EntityIn, EntityMergeIn, EntityOut, EntitySuggestion, ReasonIn

router = APIRouter(prefix="/projects/{slug}/entities", tags=["memory"])

ENTITY_NOT_FOUND = "Entité introuvable"


async def _serialize(session: AsyncSession, rows: list[Entity]) -> list[EntityOut]:
    aliases = await entity_service.aliases_of(session, [e.id for e in rows])
    return [
        EntityOut(
            id=e.id,
            name=e.name,
            kind=e.kind,
            merged_into_id=e.merged_into_id,
            aliases=[
                EntityAliasOut(alias=a.alias, merged_from_id=a.merged_from_id) for a in aliases.get(e.id, [])
            ],
            created_at=e.created_at,
        )
        for e in rows
    ]


async def _entity(session: AsyncSession, project_id: uuid.UUID, entity_id: uuid.UUID) -> Entity:
    entity = await session.get(Entity, entity_id)
    if entity is None or entity.project_id != project_id:
        raise not_found(ENTITY_NOT_FOUND)
    return entity


@router.get("", response_model=list[EntityOut], summary="Entités du projet et leurs alias")
async def list_entities(
    access: ViewerAccess, session: SessionDep, include_merged: bool = False
) -> list[EntityOut]:
    query = select(Entity).where(Entity.project_id == access.project_id).order_by(Entity.name)
    if not include_merged:
        query = query.where(Entity.merged_into_id.is_(None))
    return await _serialize(session, list(await session.scalars(query)))


@router.post("", response_model=EntityOut, status_code=status.HTTP_201_CREATED, summary="Créer une entité")
async def create_entity(body: EntityIn, access: EditorAccess, session: SessionDep) -> EntityOut:
    entity = await entity_service.create_entity(
        session,
        access.project_id,
        body.name,
        kind=body.kind,
        aliases=body.aliases,
        actor=access.principal.actor,
    )
    await session.commit()
    return (await _serialize(session, [entity]))[0]


@router.get("/suggestions", response_model=list[EntitySuggestion], summary="Fusions suggérées")
async def merge_suggestions(access: EditorAccess, session: SessionDep) -> list[EntitySuggestion]:
    found = await entity_service.suggestions(session, access.project_id)
    serialized = {
        e.id: e
        for e in await _serialize(session, list({x.id: x for s in found for x in (s.a, s.b)}.values()))
    }
    return [
        EntitySuggestion(a=serialized[s.a.id], b=serialized[s.b.id], score=s.score, reason=s.reason)
        for s in found
    ]


@router.post("/{entity_id}/merge", response_model=EntityOut, summary="Fusionner une entité dans celle-ci")
async def merge_entity(
    entity_id: uuid.UUID, body: EntityMergeIn, access: EditorAccess, session: SessionDep
) -> EntityOut:
    target = await _entity(session, access.project_id, entity_id)
    source = await _entity(session, access.project_id, body.source_id)
    await entity_service.merge(session, target, source, access.principal.actor, body.reason)
    await session.commit()
    await session.refresh(target)
    return (await _serialize(session, [target]))[0]


@router.post("/{entity_id}/unmerge", response_model=EntityOut, summary="Annuler la fusion de cette entité")
async def unmerge_entity(
    entity_id: uuid.UUID, body: ReasonIn, access: EditorAccess, session: SessionDep
) -> EntityOut:
    source = await _entity(session, access.project_id, entity_id)
    await entity_service.unmerge(session, source, access.principal.actor, body.reason)
    await session.commit()
    await session.refresh(source)
    return (await _serialize(session, [source]))[0]
