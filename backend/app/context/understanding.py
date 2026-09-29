"""``understand`` stage (ARCHITECTURE §9.1): task normalisation, intent, key terms, query embedding."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.context.textutils import fold, key_terms, normalize_whitespace
from app.enums import AgentKind, Intent

logger = logging.getLogger("orbit.context.understand")

#: The query embedding must never block a request for long (a cold local model loads lazily).
EMBED_TIMEOUT_SECONDS = 20.0

#: Folded keyword stems per intent (matched as substrings of the folded task).
INTENT_KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.specification: (
        "specification",
        "spec ",
        "specs",
        "rediger",
        "redaction",
        "user stor",
        "exigence",
        "cahier des charges",
        "fonctionnel",
        "perimetre",
        "backlog",
        "epic",
    ),
    Intent.design: (
        "design",
        "maquette",
        "parcours",
        "ux",
        "ui ",
        "wireframe",
        "figma",
        "ergonom",
        "prototype",
        "ecran",
        "interface",
    ),
    Intent.engineering: (
        "architecture",
        "implement",
        "code",
        "api",
        "technique",
        "developp",
        "deploi",
        "infrastructure",
        "base de donnees",
        "sso",
        "oidc",
        "integration",
        "securite",
        "performance",
    ),
    Intent.research: ("recherche", "benchmark", "veille", "entretien", "etude", "etat de l'art", "interview"),
    Intent.analysis: (
        "analys",
        "synthese",
        "compar",
        "indicateur",
        "kpi",
        "tendance",
        "statistique",
        "bilan",
    ),
    Intent.validation: (
        "valider",
        "validation",
        "verifier",
        "recette",
        "tester",
        "test ",
        "critere",
        "conformite",
        "controle",
        "audit",
    ),
}

AGENT_KIND_INTENTS: dict[AgentKind, Intent] = {
    AgentKind.product: Intent.specification,
    AgentKind.design: Intent.design,
    AgentKind.engineering: Intent.engineering,
    AgentKind.research: Intent.research,
}


@dataclass(slots=True)
class Understanding:
    task: str
    intent: Intent
    intent_inferred: bool
    terms: list[str]
    query_vector: list[float] | None
    embedding_model: str | None
    warnings: list[str] = field(default_factory=list)


def normalize_task(task: str) -> str:
    return normalize_whitespace(task)


def infer_intent(task: str, agent_kind: AgentKind | str | None = None) -> Intent:
    """Keyword-based intent; ties broken by the agent kind, then by the declaration order."""
    folded = f" {fold(task)} "
    scores = {
        intent: sum(1 for kw in keywords if kw in folded) for intent, keywords in INTENT_KEYWORDS.items()
    }
    best = max(scores.values())
    if best == 0:
        if agent_kind is not None:
            try:
                return AGENT_KIND_INTENTS.get(AgentKind(agent_kind), Intent.general)
            except ValueError:
                return Intent.general
        return Intent.general
    leaders = [intent for intent, score in scores.items() if score == best]
    if agent_kind is not None and len(leaders) > 1:
        try:
            preferred = AGENT_KIND_INTENTS.get(AgentKind(agent_kind))
        except ValueError:
            preferred = None
        if preferred in leaders:
            return preferred  # type: ignore[return-value]
    return leaders[0]


async def embed_query(text: str) -> tuple[list[float] | None, str | None]:
    """Query vector and model name; ``(None, None)`` when no embedder is available."""
    try:
        from app.search.embeddings import get_embedder

        embedder = await asyncio.to_thread(get_embedder)
        vector = await asyncio.wait_for(embedder.embed_query(text), timeout=EMBED_TIMEOUT_SECONDS)
        return [float(x) for x in vector], str(getattr(embedder, "model_name", "") or "") or None
    except NotImplementedError:
        logger.debug("Embedder not available yet: dense retrieval disabled")
    except Exception as exc:
        logger.warning("Query embedding failed (dense retrieval disabled for this request): %s", exc)
    return None, None


async def understand(task: str, intent: Intent | None, agent_kind: AgentKind | str | None) -> Understanding:
    normalized = normalize_task(task)
    resolved = intent or infer_intent(normalized, agent_kind)
    vector, model = await embed_query(normalized)
    return Understanding(
        task=normalized,
        intent=resolved,
        intent_inferred=intent is None,
        terms=key_terms(normalized),
        query_vector=vector,
        embedding_model=model,
    )
