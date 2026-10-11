"""Validated learnings (ORION): an improvement verified by an evaluation, stored with where it applies.

A learning is a memory item of kind ``learning``. Its ``learning_meta`` carries ``applies_to`` (task types,
agent kinds, skills, tools, agent versions; an empty list means « all ») and ``evidence`` (the experiment,
the runs, the metric, the baseline and candidate scores). ORBIT only serves a learning to requests it
applies to; skills, tools and agent versions are metadata for the consumer (ORBIT does not know them).

Everything here is pure (no I/O).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.enums import AgentKind, Intent


def _enum_values(raw: Any, enum_cls: type[Intent] | type[AgentKind]) -> list[str]:
    out: list[str] = []
    for value in raw or []:
        text = str(getattr(value, "value", value))
        if text in enum_cls.__members__ and text not in out:
            out.append(text)
    return out


def _strings(raw: Any, limit: int) -> list[str]:
    return list(dict.fromkeys(str(v).strip()[:120] for v in (raw or []) if str(v).strip()))[:limit]


def normalize_meta(applies_to: Any, evidence: Any) -> dict[str, Any]:
    """Stored ``learning_meta`` from validated input (pydantic models or mappings)."""
    scope: Mapping[str, Any] = applies_to if isinstance(applies_to, Mapping) else applies_to.model_dump()
    proof: dict[str, Any] = (
        dict(evidence) if isinstance(evidence, Mapping) else evidence.model_dump(mode="json")
    )
    proof["delta"] = round(float(proof["candidate"]) - float(proof["baseline"]), 4)
    return {
        "applies_to": {
            "task_types": _enum_values(scope.get("task_types"), Intent),
            "agent_kinds": _enum_values(scope.get("agent_kinds"), AgentKind),
            "skills": _strings(scope.get("skills"), 20),
            "tools": _strings(scope.get("tools"), 20),
            "agent_versions": _strings(scope.get("agent_versions"), 20),
        },
        "evidence": proof,
    }


def applies_to(
    meta: Mapping[str, Any] | None, intent: str | None, agent_kind: str | None
) -> tuple[bool, str]:
    """Whether a learning applies to a request; ``(False, reason)`` explains a mismatch (French)."""
    scope = (meta or {}).get("applies_to") or {}
    task_types = list(scope.get("task_types") or [])
    agent_kinds = list(scope.get("agent_kinds") or [])
    if task_types and intent and intent not in task_types and Intent.general.value not in task_types:
        return False, f"apprentissage réservé aux tâches {', '.join(task_types)} (tâche : {intent})"
    if agent_kinds and agent_kind and agent_kind not in agent_kinds:
        return False, f"apprentissage réservé aux agents {', '.join(agent_kinds)} (agent : {agent_kind})"
    return True, ""
