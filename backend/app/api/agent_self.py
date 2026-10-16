"""``GET /agents/self``: the identity behind an agent API key (not project-scoped, keys only)."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentPrincipal, SessionDep
from app.errors import forbidden, not_found
from app.models import Project
from app.schemas.agents import AgentSelf, AgentSelfKey, AgentSelfProject
from app.services import workspaces

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get(
    "/self", response_model=AgentSelf, summary="Identité, projet et statut de la clé d'agent appelante"
)
async def agent_self(principal: CurrentPrincipal, session: SessionDep) -> AgentSelf:
    agent = principal.agent
    if agent is None:
        raise forbidden("Cette ressource décrit une clé d'agent : appelez-la avec une clé d'agent")
    project = await session.get(Project, agent.project_id)
    if project is None or not workspaces.allows(agent.workspace_id, project.workspace_id, surface="project"):
        raise not_found("Projet de l'agent introuvable")
    return AgentSelf(
        id=agent.id,
        name=agent.name,
        kind=agent.kind,
        description=agent.description,
        clearance=int(agent.clearance),
        project=AgentSelfProject(id=project.id, slug=project.slug, name=project.name),
        key=AgentSelfKey(
            prefix=agent.api_key_prefix, created_at=agent.created_at, last_used_at=agent.last_used_at
        ),
    )
