"""Hybrid retrieval: BM25 + k-NN run concurrently, fused with Reciprocal Rank Fusion (ARCHITECTURE §9.3).

``rrf(d) = Σ 1 / (k + rank_i(d))`` over the lists where ``d`` appears (ranks are 1-based, ``k = 60``).
``rrf_norm`` divides by the best fused score of the result set so the top hit is ``1.0`` (0 when
nothing is found). ``dense_score`` is the cosine similarity (0..1) returned by
:func:`app.search.opensearch.knn_search`; ``bm25_score`` is the raw BM25 score.

Pre-filtering is **project only** (+ organisation long-term memory for ``kind="memory"``):
governance is applied by the caller so that every exclusion can be explained.

If one of the two retrievers fails (e.g. the embedding model is unavailable), the other one's
results are still returned (degraded mode, logged); if both fail the first error is raised.

``FusedHit.source`` holds the indexed fields; with ``include_embedding=True`` (default) it also
carries the stored vector under ``"embedding"`` so that the context engine can compute dense
similarities for BM25-only hits, near-duplicates (cosine > 0.92) and MMR diversity without another
round trip.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.search import opensearch
from app.search.opensearch import FilterSpec, IndexKind, OSHit

logger = logging.getLogger("orbit.hybrid")

RRF_K = 60


@dataclass(slots=True)
class FusedHit:
    """One fused candidate. Ranks are 1-based (``None`` when absent from that list)."""

    id: str
    source: dict[str, Any] = field(default_factory=dict)
    bm25_score: float | None = None
    bm25_rank: int | None = None
    dense_score: float | None = None
    dense_rank: int | None = None
    rrf: float = 0.0
    rrf_norm: float = 0.0

    @property
    def best_rank(self) -> int:
        ranks = [r for r in (self.bm25_rank, self.dense_rank) if r is not None]
        return min(ranks) if ranks else 1_000_000


def reciprocal_rank_fusion(
    bm25_hits: Sequence[OSHit], dense_hits: Sequence[OSHit], *, k: int = RRF_K
) -> list[FusedHit]:
    """Fuse two ranked hit lists with RRF (pure function, no I/O)."""
    fused: dict[str, FusedHit] = {}
    for rank, hit in enumerate(bm25_hits, start=1):
        item = fused.setdefault(hit.id, FusedHit(id=hit.id, source=dict(hit.source)))
        if item.bm25_rank is None:
            item.bm25_rank = rank
            item.bm25_score = hit.score
            item.rrf += 1.0 / (k + rank)
    for rank, hit in enumerate(dense_hits, start=1):
        item = fused.setdefault(hit.id, FusedHit(id=hit.id, source=dict(hit.source)))
        if not item.source:
            item.source = dict(hit.source)
        if item.dense_rank is None:
            item.dense_rank = rank
            item.dense_score = hit.score
            item.rrf += 1.0 / (k + rank)
    results = sorted(fused.values(), key=lambda h: (-h.rrf, h.best_rank, h.id))
    best = results[0].rrf if results else 0.0
    for item in results:
        item.rrf_norm = round(item.rrf / best, 6) if best > 0 else 0.0
    return results


async def hybrid_search(
    kind: IndexKind,
    query_text: str,
    query_vector: Sequence[float] | None,
    *,
    project_id: str | uuid.UUID,
    size_each: int = 40,
    filters: FilterSpec = None,
    include_org_memory: bool = True,
    k: int = RRF_K,
    include_embedding: bool = True,
) -> list[FusedHit]:
    """Run BM25 and k-NN concurrently on ``kind`` and fuse them with RRF.

    ``query_vector`` may be ``None``: the query is then embedded with the configured embedder.
    Results are ordered by fused score (best first).
    """
    pid = str(project_id)

    async def _bm25() -> list[OSHit]:
        return await opensearch.bm25_search(
            kind,
            query_text,
            project_id=pid,
            size=size_each,
            filters=filters,
            include_org_memory=include_org_memory,
            include_embedding=include_embedding,
        )

    async def _dense() -> list[OSHit]:
        vector = query_vector
        if vector is None:
            if not (query_text or "").strip():
                return []
            from app.search.embeddings import aget_embedder

            embedder = await aget_embedder()
            vector = await embedder.embed_query(query_text)
        return await opensearch.knn_search(
            kind,
            vector,
            project_id=pid,
            size=size_each,
            filters=filters,
            include_org_memory=include_org_memory,
            include_embedding=include_embedding,
        )

    bm25_result, dense_result = await asyncio.gather(_bm25(), _dense(), return_exceptions=True)
    errors = [r for r in (bm25_result, dense_result) if isinstance(r, BaseException)]
    for error in errors:
        if isinstance(error, asyncio.CancelledError):
            raise error
    if len(errors) == 2:
        raise errors[0]
    if isinstance(bm25_result, BaseException):
        logger.warning("BM25 retrieval failed on %s (dense only): %s", kind, bm25_result)
        bm25_hits: list[OSHit] = []
    else:
        bm25_hits = bm25_result
    if isinstance(dense_result, BaseException):
        logger.warning("k-NN retrieval failed on %s (BM25 only): %s", kind, dense_result)
        dense_hits: list[OSHit] = []
    else:
        dense_hits = dense_result
    return reciprocal_rank_fusion(bm25_hits, dense_hits, k=k)
