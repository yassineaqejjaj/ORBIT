"""Context sufficiency (docs/AI_CONTEXT_ENGINEERING.md §C5): is the served context enough to answer?

Deterministic, no LLM. Reuses the sub-questions of chantier B (``query_rewrite`` decomposition and
its coverage test): a sub-topic is covered when one served item contains at least half of its key
terms. The score combines

* sub-topic coverage (the task itself when it was not decomposed),
* key-term coverage of the task over everything served,
* the relevance of the best served items (final scores),

and the verdict is ``sufficient`` (≥ the sufficient threshold, nothing missing), ``partial`` (≥ the
partial threshold, or sufficient with a missing sub-topic) or ``insufficient``. Missing sub-topics are
returned so an agent can run ``search_more`` and *Demander à ORBIT* can answer « je ne sais pas ».
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.config import settings
from app.context import query_rewrite
from app.context.textutils import key_terms, words
from app.schemas.context import ContextSufficiency

if TYPE_CHECKING:
    from app.context.selection import Decision

SUFFICIENT = "sufficient"
PARTIAL = "partial"
INSUFFICIENT = "insufficient"
TOP_ITEMS = 3


def assess(
    task: str,
    subtopics: Sequence[str],
    included: Sequence[Decision],
    *,
    sufficient_threshold: float | None = None,
) -> ContextSufficiency:
    high = settings.sufficiency_sufficient_threshold if sufficient_threshold is None else sufficient_threshold
    low = min(settings.sufficiency_partial_threshold, high)
    texts = [f"{d.candidate.title}. {d.candidate.text}" for d in included]
    topics = [t for t in subtopics if key_terms(t)]
    if not included:
        return ContextSufficiency(
            score=0.0,
            verdict=INSUFFICIENT,
            missing_subtopics=list(subtopics) or [task],
            covered_subtopics=[],
            explanation="Aucun élément pertinent et autorisé n'a été retenu.",
        )
    terms = key_terms(task)
    served_words = {w for text in texts for w in words(text)}
    term_coverage = (
        sum(1 for t in terms if any(w.startswith(t) or t.startswith(w) for w in served_words if len(w) > 2))
        / len(terms)
        if terms
        else 1.0
    )
    if topics:
        missing = query_rewrite.uncovered(topics, texts)
        covered = [t for t in topics if t not in missing]
        topic_coverage = len(covered) / len(topics)
    else:  # task not decomposed: the task is the only sub-topic, covered by the served items together
        covered, missing = ([task], []) if term_coverage >= query_rewrite.COVERAGE_THRESHOLD else ([], [task])
        topics = [task]
        topic_coverage = term_coverage
    best = sorted((max(0.0, min(1.0, d.candidate.score)) for d in included), reverse=True)[:TOP_ITEMS]
    relevance = sum(best) / len(best) if best else 0.0
    score = round(0.5 * topic_coverage + 0.25 * term_coverage + 0.25 * relevance, 3)
    if score >= high and not missing:
        verdict = SUFFICIENT
    elif score >= low:
        verdict = PARTIAL
    else:
        verdict = INSUFFICIENT
    explanation = (
        f"{len(covered)}/{len(topics)} sous-sujet(s) couvert(s), {round(term_coverage * 100)} % des termes "
        f"de la tâche présents, pertinence des meilleurs éléments {relevance:.2f}"
    )
    return ContextSufficiency(
        score=score,
        verdict=verdict,
        missing_subtopics=missing,
        covered_subtopics=covered,
        explanation=explanation,
    )
