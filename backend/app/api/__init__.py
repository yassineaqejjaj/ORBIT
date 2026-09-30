"""REST API v1 routers (mounted under ``/api/v1`` by ``app.main``)."""

from fastapi import APIRouter

from app.api import (
    account,
    agents,
    audit,
    auth,
    compliance,
    connectors,
    context,
    documents,
    evaluation,
    jobs,
    members,
    memory,
    meta,
    metrics,
    ops,
    projects,
    search,
    sessions,
    snapshots,
    sources,
    users,
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
    evaluation,
    jobs,
    search,
    memory,
    sessions,
    context,
    snapshots,
    metrics,
    audit,
    meta,
    account,
    compliance,
    ops,
    connectors,
    evaluation,
):
    api_router.include_router(module.router)

__all__ = ["API_PREFIX", "api_router"]
