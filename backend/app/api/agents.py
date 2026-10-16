"""Project agents and their API keys (the full key is only returned once)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.db import utcnow
from app.deps import OwnerAccess, ProjectAccess, SessionDep, ViewerAccess
from app.enums import classification_code
from app.errors import conflict, forbidden, not_found
from app.models import Agent
from app.schemas import Agent as AgentOut
from app.schemas import AgentCreated, AgentCreateIn, AgentRotateIn
from app.security import generate_api_key
from app.services import audit
from app.services.audit import AuditAction

router = APIRouter(prefix="/projects/{slug}/agents", tags=["agents"])


async def _get_agent(session: SessionDep, access: ProjectAccess, agent_id: uuid.UUID) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.project_id != access.project_id:
        raise not_found("Agent introuvable")
    return agent


@router.get("", response_model=list[AgentOut], summary="Agents du projet")
async def list_agents(access: ViewerAccess, session: SessionDep) -> list[AgentOut]:
    rows = await session.scalars(
        select(Agent)
        .where(Agent.project_id == access.project_id)
        .order_by(Agent.active.desc(), Agent.created_at)
    )
    return [AgentOut.model_validate(a) for a in rows]


@router.post("", response_model=AgentCreated, status_code=status.HTTP_201_CREATED, summary="Créer un agent")
async def create_agent(body: AgentCreateIn, access: OwnerAccess, session: SessionDep) -> AgentCreated:
    principal = access.principal
    if not principal.is_admin and body.clearance > principal.clearance:
        raise forbidden(
            f"L'habilitation d'un agent ({classification_code(body.clearance)}) ne peut pas dépasser "
            f"la vôtre ({classification_code(principal.clearance)})"
        )
    key = generate_api_key()
    agent = Agent(
        project_id=access.project_id,
        workspace_id=access.project.workspace_id,
        name=body.name,
        kind=body.kind,
        description=body.description,
        clearance=body.clearance,
        api_key_prefix=key.prefix,
        api_key_hash=key.key_hash,
        active=True,
        created_by=principal.user_id,
        role=body.role,
        expires_at=utcnow() + timedelta(days=body.expires_in_days) if body.expires_in_days else None,
    )
    session.add(agent)
    await session.flush()
    await audit.record(
        session,
        access.project_id,
        principal,
        AuditAction.agent_create,
        "agent",
        agent.id,
        summary=f"Création de l'agent « {agent.name} » ({classification_code(agent.clearance)})",
        details={
            "kind": agent.kind,
            "clearance": agent.clearance,
            "role": agent.role,
            "expires_at": agent.expires_at,
            "api_key_prefix": agent.api_key_prefix,
        },
    )
    await session.commit()
    return AgentCreated(agent=AgentOut.model_validate(agent), api_key=key.key)


@router.post("/{agent_id}/rotate", response_model=AgentCreated, summary="Renouveler la clé d'un agent")
async def rotate_agent_key(
    agent_id: uuid.UUID, access: OwnerAccess, session: SessionDep, body: AgentRotateIn | None = None
) -> AgentCreated:
    """New secret, same workspace / project / role / clearance. This is also how an expired key is renewed."""
    agent = await _get_agent(session, access, agent_id)
    if not agent.active:
        raise conflict("Cet agent est révoqué : créez un nouvel agent")
    previous_prefix = agent.api_key_prefix
    key = generate_api_key()
    agent.api_key_prefix = key.prefix
    agent.api_key_hash = key.key_hash
    agent.rotated_at = utcnow()
    if body is not None and body.expires_in_days:
        agent.expires_at = utcnow() + timedelta(days=body.expires_in_days)
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.agent_rotate,
        "agent",
        agent.id,
        summary=f"Renouvellement de la clé de l'agent « {agent.name} »",
        details={"previous_prefix": previous_prefix, "api_key_prefix": key.prefix},
    )
    await session.commit()
    return AgentCreated(agent=AgentOut.model_validate(agent), api_key=key.key)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Révoquer un agent")
async def revoke_agent(agent_id: uuid.UUID, access: OwnerAccess, session: SessionDep) -> Response:
    agent = await _get_agent(session, access, agent_id)
    if agent.active:
        agent.active = False
        await audit.record(
            session,
            access.project_id,
            access.principal,
            AuditAction.agent_revoke,
            "agent",
            agent.id,
            summary=f"Révocation de l'agent « {agent.name} »",
            details={"api_key_prefix": agent.api_key_prefix},
        )
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
