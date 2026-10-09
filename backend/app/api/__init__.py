"""REST API v1 routers (mounted under ``/api/v1`` by ``app.main``)."""

from fastapi import APIRouter

from app.api import (
    a2a,
    agents,
    ask,
    audit,
    auth,
    compliance,
    connectors,
    context,
    documents,
    entities,
    evaluation,
    events,
    feed,
    inbox,
    jobs,
    members,
    memory,
    meta,
    metrics,
    projects,
    search,
    sessions,
    skills,
    snapshots,
    sources,
    teams,
    users,
    webhooks,
)

API_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_PREFIX)
for module in (
    auth,
    users,
    projects,
    members,
    agents,
    sources,
    documents,
    jobs,
    search,
    memory,
    skills,
    entities,
    sessions,
    context,
    snapshots,
    metrics,
    audit,
    meta,
    inbox,
    feed,
    events,
    webhooks,
    ask,
    teams,
    connectors,
    compliance,
    evaluation,
    a2a,
):
    api_router.include_router(module.router)

__all__ = ["API_PREFIX", "api_router"]
