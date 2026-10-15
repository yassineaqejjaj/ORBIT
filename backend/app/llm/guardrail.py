"""LLM guardrail (docs/FEATURES.md « Garde-fou LLM »), shared by every LLM call site.

* Content classified above ``ORBIT_LLM_MAX_CLASSIFICATION`` (default C1) is **never** sent to an external
  LLM; ``ORBIT_LLM_LOCAL=true`` (self-hosted model) lifts the ceiling. Callers fall back to the
  deterministic path and every skip is counted in ``orbit_llm_guardrail_skips_total{reason}``.
* The same ceiling applies to **remote embedding providers** (``ORBIT_EMBEDDING_PROVIDER=openai``): a text
  above it is never sent (``reason="embedding"``), see :func:`app.search.embeddings.embed_documents_guarded`.
  ``ORBIT_LLM_LOCAL=true`` also declares the embedding service self-hosted.
* An unknown level (``None``) is always treated as C3.
* With ``ORBIT_LLM_REDACT_PII=true`` (default) personal data is masked before leaving ORBIT.
"""

from __future__ import annotations

from prometheus_client import Counter

from app.config import settings
from app.ingestion import pii

#: ``classification``: content above the ceiling; ``embedding``: text withheld from a remote embedding
#: provider (same ceiling); ``disabled``: no LLM configured (not counted as a leak,
#: only for completeness of dashboards); ``error``: provider failure handled by the deterministic fallback.
LLM_GUARDRAIL_SKIPS = Counter(
    "orbit_llm_guardrail_skips_total",
    "LLM calls (or items) skipped by the ORBIT guardrail, by reason",
    ["reason"],
)

REASON_CLASSIFICATION = "classification"
REASON_ERROR = "error"
REASON_EMBEDDING = "embedding"
MAX_LEVEL = 3


def ceiling() -> int:
    """Highest classification level that may be sent to the configured LLM."""
    return MAX_LEVEL if settings.llm_local else int(settings.llm_max_classification)


def allows(classification: int | None) -> bool:
    """``True`` when content of this level may be sent to the LLM (unknown level ⇒ treated as C3)."""
    level = MAX_LEVEL if classification is None else int(classification)
    return level <= ceiling()


def record_skip(reason: str = REASON_CLASSIFICATION, count: int = 1) -> None:
    if count > 0:
        LLM_GUARDRAIL_SKIPS.labels(reason=reason).inc(count)


def skip_count(reason: str = REASON_CLASSIFICATION) -> float:
    """Current value of the skip counter (tests, diagnostics)."""
    return LLM_GUARDRAIL_SKIPS.labels(reason=reason)._value.get()


def prepare(text: str) -> str:
    """Text as it may leave ORBIT: PII masked when ``ORBIT_LLM_REDACT_PII`` is on."""
    if not text or not settings.llm_redact_pii:
        return text
    return pii.analyze(text).redacted


__all__ = [
    "LLM_GUARDRAIL_SKIPS",
    "REASON_CLASSIFICATION",
    "REASON_EMBEDDING",
    "REASON_ERROR",
    "allows",
    "ceiling",
    "prepare",
    "record_skip",
    "skip_count",
]
