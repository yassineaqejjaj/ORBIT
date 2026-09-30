"""Agent API-key scopes (docs/PRODUCTION.md §3) and their mapping to agent-accessible endpoints."""

from __future__ import annotations

from enum import StrEnum


class AgentScope(StrEnum):
    context_read = "context:read"
    search_read = "search:read"
    snapshots_read = "snapshots:read"
    memory_propose = "memory:propose"
    sessions_write = "sessions:write"
    documents_write = "documents:write"
    feedback_write = "feedback:write"


ALL_SCOPES: tuple[AgentScope, ...] = tuple(AgentScope)
#: Default scopes of a new key: everything except corpus writes (``documents:write``).
DEFAULT_SCOPES: tuple[AgentScope, ...] = tuple(s for s in AgentScope if s is not AgentScope.documents_write)
DEFAULT_SCOPE_VALUES: list[str] = [s.value for s in DEFAULT_SCOPES]

SCOPE_LABELS: dict[AgentScope, str] = {
    AgentScope.context_read: "assembler des contextes",
    AgentScope.search_read: "rechercher dans le corpus",
    AgentScope.snapshots_read: "lire les snapshots",
    AgentScope.memory_propose: "proposer des éléments de mémoire",
    AgentScope.sessions_write: "gérer les sessions de travail",
    AgentScope.documents_write: "ajouter des documents",
    AgentScope.feedback_write: "évaluer les contextes servis",
}

#: First path segment after ``/projects/{slug}/`` -> scope required from an agent key.
_SEGMENT_SCOPES: dict[str, AgentScope] = {
    "context": AgentScope.context_read,
    "search": AgentScope.search_read,
    "snapshots": AgentScope.snapshots_read,
    "memory": AgentScope.memory_propose,
    "sessions": AgentScope.sessions_write,
    "documents": AgentScope.documents_write,
    "sources": AgentScope.documents_write,
    "feedback": AgentScope.feedback_write,
}


def scope_for_route(route_path: str) -> AgentScope | None:
    """Scope required for an agent calling the route template ``route_path`` (``None`` = not agent-callable).

    Unknown routes return ``None`` so that the caller denies them (fail closed).
    """
    marker = "/projects/{slug}/"
    index = route_path.find(marker)
    if index < 0:
        return None
    rest = route_path[index + len(marker) :].strip("/")
    segments = rest.split("/")
    if segments[0] == "context" and "feedback" in segments:
        return AgentScope.feedback_write
    return _SEGMENT_SCOPES.get(segments[0])


def normalize_scopes(values: list[str] | None) -> list[str]:
    """Deduplicated, validated, canonical-order scope list."""
    if values is None:
        return list(DEFAULT_SCOPE_VALUES)
    wanted = {AgentScope(v).value for v in values}
    return [s.value for s in AgentScope if s.value in wanted]
