"""Reranking (ARCHITECTURE §9.4).

``heuristic`` (default)::

    score = 0.55·rrf_norm + 0.20·dense + 0.10·freshness + 0.10·type_boost + 0.05·term_overlap

with freshness = exponential decay (half-life 90 days) and type boost = validated decision 1.0,
requirement/constraint 0.8, chunk 0.5 (other kinds in between).

``fastembed``: a cross-encoder (``fastembed.rerank.cross_encoder.TextCrossEncoder``,
``ORBIT_RERANKER_MODEL``) scores the best candidates; its sigmoid-normalised relevance is blended with
``rrf_norm`` and the same combination is applied. Any model failure falls back to the heuristic.

``none``: the fused retrieval score is used as is.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.config import settings
from app.enums import CandidateType, MemoryKind, MemoryStatus
from app.governance import freshness
from app.governance.policy import Candidate
from app.context.textutils import cosine, term_overlap

logger = logging.getLogger("orbit.context.rerank")

W_RRF = 0.55
W_DENSE = 0.20
W_FRESHNESS = 0.10
W_TYPE = 0.10
W_TERMS = 0.05

#: Weight of the cross-encoder relevance vs. the fused retrieval rank when ``ORBIT_RERANKER=fastembed``.
CROSS_ENCODER_BLEND = 0.5
#: Only the best candidates (by heuristic score) are sent to the cross-encoder (latency bound).
CROSS_ENCODER_TOP_N = 30
CROSS_ENCODER_MAX_CHARS = 1200
CROSS_ENCODER_TIMEOUT_SECONDS = 8.0

TYPE_BOOST_CHUNK = 0.5
TYPE_BOOST_SESSION = 0.5
_TYPE_BOOST_MEMORY: dict[MemoryKind, float] = {
    MemoryKind.decision: 0.85,  # validated decisions get 1.0 (see type_boost)
    MemoryKind.requirement: 0.8,
    MemoryKind.constraint: 0.8,
    MemoryKind.risk: 0.7,
    MemoryKind.fact: 0.65,
    MemoryKind.preference: 0.6,
    MemoryKind.summary: 0.6,
}
#: Proposed (not yet validated) memory items are slightly less authoritative.
PROPOSED_FACTOR = 0.9


def type_boost(candidate: Candidate) -> float:
    if candidate.candidate_type == CandidateType.chunk:
        return TYPE_BOOST_CHUNK
    if candidate.candidate_type == CandidateType.session:
        return TYPE_BOOST_SESSION
    kind = candidate.memory_kind
    if kind == MemoryKind.decision and candidate.status == MemoryStatus.validated.value:
        return 1.0
    boost = _TYPE_BOOST_MEMORY.get(kind, 0.6) if kind is not None else 0.6
    if candidate.status == MemoryStatus.proposed.value:
        boost *= PROPOSED_FACTOR
    return boost


def dense_similarity(candidate: Candidate, query_vector: Sequence[float] | None) -> float:
    """Dense relevance in ``[0, 1]``: the k-NN score when retrieved by k-NN, else the cosine of the
    stored embedding mapped like OpenSearch ``cosinesimil`` (``(1 + cos) / 2``), else 0."""
    if candidate.scores.dense is not None:
        return max(0.0, min(1.0, float(candidate.scores.dense)))
    sim = cosine(candidate.embedding, query_vector)
    if sim is None:
        return 0.0
    return max(0.0, min(1.0, (1.0 + sim) / 2.0))


def heuristic_score(relevance: float, dense: float, fresh: float, boost: float, overlap: float) -> float:
    score = W_RRF * relevance + W_DENSE * dense + W_FRESHNESS * fresh + W_TYPE * boost + W_TERMS * overlap
    return max(0.0, min(1.0, score))


def _session_relevance(candidate: Candidate) -> float:
    """Session turns are not ranked by the index: recency within the session is their relevance."""
    return float(candidate.extra.get("recency", 0.5))


def apply_heuristic(
    candidates: Sequence[Candidate],
    *,
    query_terms: Sequence[str],
    query_vector: Sequence[float] | None,
    now: datetime,
) -> None:
    """Compute every signal and the heuristic final score in place."""
    for c in candidates:
        s = c.scores
        s.freshness = freshness.decay_score(c.date, now)
        s.type_boost = type_boost(c)
        s.term_overlap = term_overlap(query_terms, f"{c.title} {c.text}")
        dense = dense_similarity(c, query_vector)
        if s.dense is None and dense > 0:
            s.dense = dense
        relevance = _session_relevance(c) if c.candidate_type == CandidateType.session else s.rrf_norm
        s.final = heuristic_score(relevance, dense, s.freshness, s.type_boost, s.term_overlap)
        s.rerank = s.final
        c.score = s.final


def apply_none(candidates: Sequence[Candidate], *, now: datetime) -> None:
    for c in candidates:
        c.scores.freshness = freshness.decay_score(c.date, now)
        relevance = _session_relevance(c) if c.candidate_type == CandidateType.session else c.scores.rrf_norm
        c.scores.final = max(0.0, min(1.0, relevance))
        c.scores.rerank = None
        c.score = c.scores.final


# --- Cross-encoder ---------------------------------------------------------------------------------

_encoder: Any = None
_encoder_failed = False
_encoder_lock = threading.Lock()


def _load_encoder() -> Any:
    global _encoder, _encoder_failed
    if _encoder is not None or _encoder_failed:
        return _encoder
    with _encoder_lock:
        if _encoder is None and not _encoder_failed:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                kwargs: dict[str, Any] = {"model_name": settings.reranker_model}
                if settings.model_cache_dir:
                    kwargs["cache_dir"] = settings.model_cache_dir
                _encoder = TextCrossEncoder(**kwargs)
                logger.info("Cross-encoder reranker loaded: %s", settings.reranker_model)
            except Exception:
                _encoder_failed = True
                logger.exception("Cross-encoder %s unavailable — heuristic reranking used", settings.reranker_model)
    return _encoder


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _cross_encode(query: str, passages: list[str]) -> list[float]:
    encoder = _load_encoder()
    if encoder is None:
        raise RuntimeError("cross-encoder unavailable")
    return [float(score) for score in encoder.rerank(query, passages, batch_size=16)]


async def apply_cross_encoder(candidates: Sequence[Candidate], *, query: str) -> bool:
    """Blend cross-encoder relevance into the best candidates (after :func:`apply_heuristic`).

    Returns ``False`` when the model could not be used (heuristic scores are kept).
    """
    pool = sorted(
        (c for c in candidates if c.candidate_type != CandidateType.session),
        key=lambda c: c.score,
        reverse=True,
    )[:CROSS_ENCODER_TOP_N]
    if not pool:
        return True
    passages = [f"{c.title}\n{c.text}"[:CROSS_ENCODER_MAX_CHARS] for c in pool]
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(_cross_encode, query, passages), timeout=CROSS_ENCODER_TIMEOUT_SECONDS
        )
    except Exception as exc:
        logger.warning("Cross-encoder reranking skipped: %s", exc)
        return False
    for c, logit in zip(pool, raw, strict=True):
        s = c.scores
        s.cross_encoder = _sigmoid(logit)
        relevance = (1 - CROSS_ENCODER_BLEND) * s.rrf_norm + CROSS_ENCODER_BLEND * s.cross_encoder
        dense = s.dense or 0.0
        s.final = heuristic_score(relevance, dense, s.freshness or 0.0, s.type_boost, s.term_overlap)
        s.rerank = s.cross_encoder
        c.score = s.final
    return True


def reranker_label() -> str:
    mode = settings.reranker
    if mode == "fastembed":
        return f"fastembed:{settings.reranker_model}"
    if mode == "none":
        return "none"
    return "heuristic-v1"


async def rerank(
    candidates: Sequence[Candidate],
    *,
    query: str,
    query_terms: Sequence[str],
    query_vector: Sequence[float] | None,
    now: datetime,
) -> str:
    """Score all candidates in place according to ``ORBIT_RERANKER``. Returns the label actually used."""
    mode = settings.reranker
    if mode == "none":
        apply_none(candidates, now=now)
        return "none"
    apply_heuristic(candidates, query_terms=query_terms, query_vector=query_vector, now=now)
    if mode == "fastembed":
        if await apply_cross_encoder(candidates, query=query):
            return reranker_label()
        return "heuristic-v1 (repli)"
    return "heuristic-v1"
