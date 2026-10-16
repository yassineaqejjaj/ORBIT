"""Inventory of the workspace filters (ADR 001 §9, NOV-106): nothing is added without declaring its filter.

No service needed. A new table or a new route that this file does not list **fails the build** until its way of
being filtered by workspace is declared (and reviewed). The declared kinds are checked against the real schema
and the real routers, so the lists cannot silently drift.

* tables: ``direct`` (own ``workspace_id`` column), ``project`` (``project_id`` -> ``projects``: inherits the
  workspace through the project, so search indices need no new field), ``parent:<table>`` (inherits through a
  parent table), ``exempt:<why>``;
* routes: every ``/projects/{slug}/...`` route must go through ``require_project`` (the single place where the
  project's workspace is compared with the identity's); the others are listed with their filter.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi.routing import APIRoute

import app.api as api
import app.models  # noqa: F401  (registers every table)
from app.db import Base

TABLES: dict[str, str] = {
    "workspaces": "exempt:the workspace entity itself",
    "users": "direct",
    "projects": "direct",
    "agents": "direct",
    "webhooks": "direct",
    "a2a_handoffs": "project",
    "ask_conversations": "project",
    "ask_messages": "parent:ask_conversations",
    "audit_log": "exempt:project_id is NULL only for platform events (user creation); every audit route is project-scoped",
    "change_events": "project",
    "chunks": "project",
    "conflict_resolutions": "project",
    "connector_runs": "project",
    "connectors": "project",
    "context_decisions": "parent:context_requests",
    "context_feedback": "parent:context_requests",
    "context_judgements": "project",
    "context_requests": "project",
    "context_snapshots": "project",
    "document_versions": "parent:documents",
    "documents": "project",
    "entities": "project",
    "entity_aliases": "project",
    "eval_cases": "parent:eval_sets",
    "eval_runs": "project",
    "eval_sets": "project",
    "ingestion_jobs": "project",
    "integrations": "project",
    "memory_events": "parent:memory_items",
    "memory_items": "exempt:project_id is NULL only for organisation memory, which belongs to the default workspace "
    "(services.workspaces.org_memory_visible: served to its projects only under enforce)",
    "memory_provenance": "parent:memory_items",
    "project_members": "project",
    "ranking_weight_changes": "project",
    "relations": "project",
    "sources": "project",
    "subscriptions": "project",
    "tombstones": "project",
    "webhook_deliveries": "project",
}

#: Routes that are not under ``/projects/{slug}``: how each one is bound to the caller's workspace.
OTHER_ROUTES: dict[str, str] = {
    "GET /agents/self": "the key's own project; refused when the key's workspace differs from its project's",
    "POST /auth/login": "identity: the session carries the account's own workspace",
    "POST /auth/logout": "identity: no data",
    "GET /auth/me": "identity: the caller's own account",
    "POST /auth/me/onboarding/complete": "identity: the caller's own account",
    "POST /auth/me/onboarding/restart": "identity: the caller's own account",
    "GET /meta": "no tenant data",
    "GET /projects": "filtered: only the projects of the caller's workspace (workspaces.allows, surface project_list)",
    "POST /projects": "created in the creator's workspace, never a parameter",
    "GET /users": "filtered: an administrator lists the accounts of their own workspace",
    "POST /users": "created in the administrator's workspace, never a parameter",
    "PATCH /users/{user_id}": "404 for an account of another workspace",
    "POST /integrations/teams/{project_slug}": "HMAC of the project's own integration, then get_project_access",
}

#: ``/projects/{slug}`` routes that call ``get_project_access`` themselves instead of ``require_project``.
INLINE_PROJECT_ROUTES = {"GET /projects/{slug}/events/stream"}

MODULES = [
    "a2a",
    "agent_self",
    "agents",
    "ask",
    "audit",
    "auth",
    "compliance",
    "connectors",
    "context",
    "documents",
    "entities",
    "evaluation",
    "events",
    "feed",
    "inbox",
    "jobs",
    "knowledge_gaps",
    "learnings",
    "members",
    "memory",
    "meta",
    "metrics",
    "projects",
    "search",
    "sessions",
    "skills",
    "snapshots",
    "sources",
    "teams",
    "users",
    "webhooks",
]


def _routes() -> Iterator[tuple[str, APIRoute]]:
    for name in MODULES:
        for route in getattr(api, name).router.routes:
            if isinstance(route, APIRoute):
                for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                    yield f"{method} {route.path}", route


def _dependencies(route: APIRoute) -> set[str]:
    found: set[str] = set()

    def walk(dependant: Any) -> None:
        for dep in dependant.dependencies:
            found.add(getattr(dep.call, "__qualname__", str(dep.call)))
            walk(dep)

    walk(route.dependant)
    return found


def test_every_table_declares_how_it_is_filtered_by_workspace() -> None:
    tables = Base.metadata.tables
    undeclared = sorted(set(tables) - set(TABLES))
    assert not undeclared, (
        f"new table(s) without a declared workspace filter: {undeclared}. Add a workspace_id column "
        "(`direct`), a project_id FK (`project`), a parent FK (`parent:<table>`) or a reviewed exemption."
    )
    assert not sorted(set(TABLES) - set(tables)), "declared tables that no longer exist"
    for name, kind in TABLES.items():
        table = tables[name]
        targets = {fk.parent.name: fk.column.table.name for fk in table.foreign_keys}
        if kind == "direct":
            assert "workspace_id" in table.c and not table.c["workspace_id"].nullable, name
            assert targets.get("workspace_id") == "workspaces", name
        elif kind == "project":
            assert targets.get("project_id") == "projects" and not table.c["project_id"].nullable, name
        elif kind.startswith("parent:"):
            assert kind.removeprefix("parent:") in targets.values(), name
            assert TABLES[kind.removeprefix("parent:")] in ("project",) or TABLES[
                kind.removeprefix("parent:")
            ].startswith("exempt:"), f"{name}: the parent must itself resolve to a project"
        else:
            assert kind.startswith("exempt:") and len(kind) > len("exempt:") + 20, (
                f"{name}: justify the exemption"
            )
    direct = {name for name, kind in TABLES.items() if kind == "direct"}
    assert direct == {name for name, t in tables.items() if "workspace_id" in t.c} - {"workspaces"}


def test_the_search_indices_carry_no_workspace_field() -> None:
    """Search is filtered through ``project_id`` (indices are never reindexed for workspaces)."""
    from app.search import opensearch

    for kind in ("chunks", "memory"):
        properties = opensearch.mapping_for(kind)["properties"]  # type: ignore[arg-type]
        assert "project_id" in properties and "workspace_id" not in properties


def test_every_route_declares_how_it_is_filtered_by_workspace() -> None:
    declared = set(OTHER_ROUTES) | INLINE_PROJECT_ROUTES
    seen: set[str] = set()
    problems: list[str] = []
    for key, route in _routes():
        seen.add(key)
        if "{slug}" in route.path and key not in INLINE_PROJECT_ROUTES:
            if not any("require_project" in dep for dep in _dependencies(route)):
                problems.append(f"{key}: a project route without require_project")
        elif key not in declared:
            problems.append(f"{key}: not under /projects/{{slug}} and not declared in OTHER_ROUTES")
    assert not problems, "\n".join(problems)
    assert not sorted(declared - seen), f"declared routes that no longer exist: {sorted(declared - seen)}"
