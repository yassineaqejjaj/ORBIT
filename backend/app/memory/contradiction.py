"""Model-based contradiction detection (docs/AI_CONTEXT_ENGINEERING.md §D3).

Complements the lexical divergence markers of :mod:`app.memory.conflicts` for two similar memory items:

1. **local NLI** — optional hook ``ORBIT_MEMORY_NLI_MODEL`` = ``package.module:function`` called as
   ``fn(premise, hypothesis) -> P(contradiction)`` in a worker thread (local model: no guardrail needed);
2. **LLM judge** — when no NLI hook is configured, an LLM is enabled and the guardrail allows the
   higher classification of the pair (C2/C3 are never sent to an external LLM, PII masked);
3. **lexical markers** — always computed; the fallback when no model is available or a model fails.

A conflict is flagged when the model's probability reaches ``ORBIT_MEMORY_CONTRADICTION_THRESHOLD`` or a
lexical marker is found; the method, score and a French explanation are stored on the relation.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.llm import client as llm_client
from app.llm import guardrail
from app.memory.conflicts import divergences, join_markers

logger = logging.getLogger(__name__)

METHOD_NLI = "nli"
METHOD_LLM = "llm"
METHOD_LEXICAL = "lexical"
NLI_TIMEOUT_SECONDS = 5.0

LLM_SYSTEM = (
    "Tu compares deux énoncés de la mémoire d'un projet (en français). Réponds en JSON : "
    '{"contradiction": true|false, "score": probabilité entre 0 et 1 que les deux énoncés soient '
    'incompatibles, "explanation": une phrase en français expliquant pourquoi}. Deux énoncés qui '
    "portent sur des sujets différents ou qui se complètent ne sont pas contradictoires."
)

NliFn = Callable[[str, str], float]
_nli_cache: dict[str, NliFn | None] = {}


@dataclass(slots=True)
class Judgement:
    contradicts: bool
    method: str
    score: float | None = None
    explanation: str = ""
    markers: list[str] = field(default_factory=list)


def nli_backend(spec: str | None = None) -> NliFn | None:
    spec = (settings.memory_nli_model if spec is None else spec).strip()
    if not spec:
        return None
    if spec not in _nli_cache:
        module_name, _, attr = spec.partition(":")
        try:
            _nli_cache[spec] = getattr(importlib.import_module(module_name), attr or "contradiction")
        except Exception as exc:  # misconfiguration: lexical / LLM fallback
            logger.warning("NLI model %s unavailable: %s", spec, exc)
            _nli_cache[spec] = None
    return _nli_cache[spec]


def _percent(score: float) -> str:
    return f"{score:.2f}".replace(".", ",")


async def _nli(fn: NliFn, a: str, b: str) -> float | None:
    try:
        # Contradiction is symmetric in intent: keep the higher of both directions.
        scores = await asyncio.wait_for(
            asyncio.gather(asyncio.to_thread(fn, a, b), asyncio.to_thread(fn, b, a)), NLI_TIMEOUT_SECONDS
        )
    except Exception as exc:
        logger.info("NLI contradiction check failed: %r", exc)
        return None
    return max(0.0, min(1.0, max(float(s) for s in scores)))


async def _llm(a: Any, b: Any) -> tuple[float, str] | None:
    level = max(int(a.classification), int(b.classification))
    if not guardrail.allows(level):
        guardrail.record_skip(guardrail.REASON_CLASSIFICATION)
        return None
    user = f"Énoncé A — {a.title} : {a.content}\n\nÉnoncé B — {b.title} : {b.content}"
    answer = await llm_client.complete_json(LLM_SYSTEM, user, classification=level, max_tokens=300)
    if not isinstance(answer, dict):
        return None
    try:
        score = float(answer.get("score", 1.0 if answer.get("contradiction") else 0.0))
    except (TypeError, ValueError):
        return None
    if answer.get("contradiction") is False:
        score = min(score, 0.5)
    explanation = " ".join(str(answer.get("explanation") or "").split())[:500]
    return max(0.0, min(1.0, score)), explanation


async def judge(a: Any, b: Any) -> Judgement:
    """Contradiction verdict for two memory items (``title``, ``content``, ``classification``)."""
    markers = divergences(a.content, b.content)
    lexical = Judgement(bool(markers), METHOD_LEXICAL, None, join_markers(markers), markers)
    mode = settings.memory_contradiction_mode
    if mode == "lexical":
        return lexical
    threshold = settings.memory_contradiction_threshold
    model: tuple[str, float, str] | None = None
    fn = nli_backend() if mode in ("auto", "nli") else None
    if fn is not None:
        score = await _nli(fn, a.content, b.content)
        if score is not None:
            model = (METHOD_NLI, score, f"Modèle NLI local : probabilité de contradiction {_percent(score)}")
    elif mode in ("auto", "llm") and llm_client.is_enabled():
        result = await _llm(a, b)
        if result is not None:
            score, why = result
            model = (
                METHOD_LLM,
                score,
                f"LLM-juge ({_percent(score)}) : {why}" if why else f"LLM-juge ({_percent(score)})",
            )
    if model is None:
        return lexical
    method, score, explanation = model
    if markers:
        explanation = f"{explanation} · marqueurs : {join_markers(markers)}"
    if score >= threshold:
        return Judgement(True, method, round(score, 3), explanation, markers)
    # Below the model threshold the lexical markers still flag (the model complements them).
    return Judgement(bool(markers), METHOD_LEXICAL, round(score, 3), explanation, markers)


__all__ = ["METHOD_LEXICAL", "METHOD_LLM", "METHOD_NLI", "Judgement", "judge", "nli_backend"]
