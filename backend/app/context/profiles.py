"""Context profiles per agent kind (docs/AI_CONTEXT_ENGINEERING.md §C3).

A profile sets, for one :class:`AgentKind`, the token budget, the sections served and their order, and
the thresholds (``min_relevance``, sufficiency). Built-in defaults are overridden per project in
``projects.settings["context_profiles"][kind]`` (edited in Paramètres). A profile applies when an agent
requests context — directly, through MCP, or simulated by the Explorer « agir en tant que » — and
explicit request parameters always win. :func:`suggest` derives an adjustment from the feedback
received by the contexts served to agents of that kind.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.packaging import SECTION_TITLES, SECTIONS
from app.db import utcnow
from app.enums import AgentKind, CandidateType, MemoryKind
from app.models import Agent, ContextDecision, ContextFeedback, ContextRequest, Project

PROFILES_KEY = "context_profiles"
SECTION_NAMES: tuple[str, ...] = tuple(name for name, _ in SECTIONS)
SUGGESTION_WINDOW_DAYS = 90
MIN_FEEDBACK = 3
#: Ratio of « irrelevant » flags over served items that suggests a stricter relevance threshold.
IRRELEVANT_RATIO = 0.15


@dataclass(slots=True)
class Profile:
    kind: AgentKind
    sections: list[str]
    token_budget: int | None = None
    min_relevance: float | None = None
    sufficient_threshold: float | None = None
    customized: bool = False

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


_ALL = list(SECTION_NAMES)
DEFAULTS: dict[AgentKind, Profile] = {
    AgentKind.product: Profile(
        AgentKind.product,
        ["decisions", "requirements", "constraints", "facts", "sources", "preferences", "session"],
        token_budget=4000,
    ),
    AgentKind.design: Profile(
        AgentKind.design,
        ["decisions", "requirements", "preferences", "constraints", "sources", "facts", "session"],
        token_budget=3000,
    ),
    AgentKind.engineering: Profile(
        AgentKind.engineering,
        ["decisions", "constraints", "sources", "facts", "requirements", "session", "preferences"],
        token_budget=6000,
    ),
    AgentKind.research: Profile(
        AgentKind.research,
        ["sources", "facts", "decisions", "requirements", "constraints", "session", "preferences"],
        token_budget=8000,
    ),
    AgentKind.custom: Profile(AgentKind.custom, list(_ALL)),
}


def _clean_sections(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    seen: list[str] = []
    for name in value:
        if isinstance(name, str) and name in SECTION_NAMES and name not in seen:
            seen.append(name)
    return seen or None


def profile_for(project: Project | None, kind: AgentKind | str) -> Profile:
    """Built-in default overridden by the project's stored profile for ``kind``."""
    agent_kind = AgentKind(kind)
    base = DEFAULTS[agent_kind]
    stored = ((project.settings or {}).get(PROFILES_KEY) or {}).get(agent_kind.value) if project else None
    if not isinstance(stored, dict):
        return Profile(**{**asdict(base), "sections": list(base.sections)})
    return Profile(
        kind=agent_kind,
        sections=_clean_sections(stored.get("sections")) or list(base.sections),
        token_budget=_int(stored.get("token_budget"), base.token_budget, 500, 32_000),
        min_relevance=_float(stored.get("min_relevance"), base.min_relevance),
        sufficient_threshold=_float(stored.get("sufficient_threshold"), base.sufficient_threshold),
        customized=True,
    )


def _int(value: Any, default: int | None, low: int, high: int) -> int | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return max(low, min(high, int(value)))
    return default


def _float(value: Any, default: float | None) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return default


def all_profiles(project: Project) -> list[Profile]:
    return [profile_for(project, kind) for kind in AgentKind]


def store(project: Project, profile: Profile) -> None:
    """Persist ``profile`` in the project settings (a new dict so SQLAlchemy sees the change)."""
    current = dict(project.settings or {})
    profiles = dict(current.get(PROFILES_KEY) or {})
    data = profile.as_dict()
    data.pop("kind")
    data.pop("customized")
    profiles[profile.kind.value] = data
    current[PROFILES_KEY] = profiles
    project.settings = current


def reset(project: Project, kind: AgentKind) -> None:
    current = dict(project.settings or {})
    profiles = dict(current.get(PROFILES_KEY) or {})
    profiles.pop(kind.value, None)
    current[PROFILES_KEY] = profiles
    project.settings = current


def section_of(candidate_type: str, memory_kind: str | None) -> str:
    """Section of a persisted decision row (same mapping as ``packaging.section_for``)."""
    if candidate_type == CandidateType.chunk.value:
        return "sources"
    if candidate_type == CandidateType.session.value:
        return "session"
    if memory_kind == MemoryKind.decision.value:
        return "decisions"
    if memory_kind == MemoryKind.requirement.value:
        return "requirements"
    if memory_kind in (MemoryKind.constraint.value, MemoryKind.risk.value):
        return "constraints"
    if memory_kind == MemoryKind.preference.value:
        return "preferences"
    return "facts"


@dataclass(slots=True)
class Suggestion:
    kind: AgentKind
    feedback_count: int = 0
    avg_rating: float | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


async def suggest(session: AsyncSession, project: Project, kind: AgentKind) -> Suggestion:
    """Adjustment suggested from the feedback on contexts served to agents of ``kind`` (90 days)."""
    profile = profile_for(project, kind)
    result = Suggestion(kind=kind)
    since = utcnow() - timedelta(days=SUGGESTION_WINDOW_DAYS)
    rows = (
        await session.execute(
            select(
                ContextFeedback.rating,
                ContextFeedback.item_flags,
                ContextRequest.id,
                ContextRequest.tokens_used,
                ContextRequest.token_budget,
            )
            .join(ContextRequest, ContextRequest.id == ContextFeedback.request_id)
            .join(Agent, Agent.id == ContextRequest.agent_id)
            .where(
                ContextRequest.project_id == project.id,
                Agent.kind == kind,
                ContextFeedback.created_at >= since,
            )
        )
    ).all()
    result.feedback_count = len(rows)
    if not rows:
        result.rationale.append("Aucun retour sur les contextes servis à ce type d'agent.")
        return result
    ratings = [int(r[0]) for r in rows]
    result.avg_rating = round(sum(ratings) / len(ratings), 2)
    if len(rows) < MIN_FEEDBACK:
        result.rationale.append(
            f"Pas assez de retours ({len(rows)} / {MIN_FEEDBACK}) pour suggérer un ajustement."
        )
        return result

    request_ids: set[uuid.UUID] = {r[2] for r in rows}
    flagged: dict[tuple[uuid.UUID, str], str] = {}
    for _rating, flags, request_id, *_ in rows:
        for flag in flags or []:
            if isinstance(flag, dict) and flag.get("citation") and flag.get("flag"):
                flagged[(request_id, str(flag["citation"]))] = str(flag["flag"])
    decisions = (
        await session.execute(
            select(
                ContextDecision.request_id,
                ContextDecision.citation,
                ContextDecision.candidate_type,
                ContextDecision.scores,
            ).where(ContextDecision.request_id.in_(request_ids), ContextDecision.included.is_(True))
        )
    ).all()
    served = Counter[str]()
    irrelevant = Counter[str]()
    outdated = 0
    for request_id, citation, candidate_type, scores in decisions:
        section = section_of(str(candidate_type), ((scores or {}).get("meta") or {}).get("memory_kind"))
        served[section] += 1
        flag = flagged.get((request_id, str(citation)))
        if flag == "irrelevant":
            irrelevant[section] += 1
        elif flag == "outdated":
            outdated += 1
    total_served = sum(served.values()) or 1
    ratio = sum(irrelevant.values()) / total_served
    base_relevance = profile.min_relevance if profile.min_relevance is not None else 0.3
    if ratio > IRRELEVANT_RATIO:
        result.changes["min_relevance"] = round(min(0.9, base_relevance + 0.05), 2)
        result.rationale.append(
            f"{round(ratio * 100)} % des éléments servis signalés « hors sujet » : "
            "seuil de pertinence relevé."
        )
    for section, count in irrelevant.items():
        if count >= MIN_FEEDBACK and count / max(served[section], 1) >= 0.5 and section in profile.sections:
            sections = [s for s in (result.changes.get("sections") or profile.sections) if s != section]
            if sections:
                result.changes["sections"] = sections
                result.rationale.append(
                    f"Section « {SECTION_TITLES[section]} » majoritairement jugée hors sujet : "
                    "retirée du profil."
                )
    fill = [r[3] / r[4] for r in rows if r[4]]
    budget = profile.token_budget or max((r[4] for r in rows if r[4]), default=4000)
    if result.avg_rating < 3.5 and fill and sum(fill) / len(fill) >= 0.9 and budget < 32_000:
        result.changes["token_budget"] = min(32_000, int(round(budget * 1.25 / 100) * 100))
        result.rationale.append(
            "Budget presque toujours épuisé et note moyenne faible : budget augmenté de 25 %."
        )
    if outdated >= MIN_FEEDBACK:
        result.rationale.append(
            f"{outdated} éléments signalés obsolètes : vérifiez les règles de fraîcheur du projet."
        )
    if not result.changes and len(result.rationale) == 0:
        result.rationale.append("Les retours ne justifient aucun ajustement.")
    return result
