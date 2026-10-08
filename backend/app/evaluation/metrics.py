"""§E1 retrieval metrics (pure functions, binary relevance).

* ``recall@k`` = |expected ∩ top-k| / |expected|;
* ``nDCG@k`` = DCG / IDCG with DCG = Σ 1/log2(rank + 1) over the expected items found in the top k
  (each expected item counted once, at its best rank) and IDCG the DCG of a perfect ranking;
* ``citation faithfulness`` = share of the citation markers ([S1], [M2]…) of the served text that point to
  an item actually served (1.0 when the text cites nothing and nothing was served, 0.0 when items were
  served but none is cited).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence

_CITATION = re.compile(r"\[([A-Z]{1,3}\d{1,4})\]")


def _found_ranks(ranked: Sequence[Iterable[str]], expected: Sequence[str], k: int) -> dict[str, int]:
    """First 1-based rank (≤ k) at which each expected key appears; ``ranked[i]`` = keys of the item."""
    wanted = set(expected)
    found: dict[str, int] = {}
    for rank, keys in enumerate(ranked[:k], start=1):
        for key in set(keys) & wanted:
            found.setdefault(key, rank)
    return found


def recall_at_k(ranked: Sequence[Iterable[str]], expected: Sequence[str], k: int) -> float:
    if not expected:
        return 1.0
    return len(_found_ranks(ranked, expected, k)) / len(set(expected))


def ndcg_at_k(ranked: Sequence[Iterable[str]], expected: Sequence[str], k: int) -> float:
    wanted = set(expected)
    if not wanted:
        return 1.0
    found = _found_ranks(ranked, expected, k)
    dcg = sum(1.0 / math.log2(rank + 1) for rank in found.values())
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(wanted), k) + 1))
    return dcg / idcg if idcg else 0.0


def cited_markers(text: str) -> list[str]:
    return _CITATION.findall(text or "")


def citation_faithfulness(text: str, served_citations: Iterable[str]) -> float:
    served = set(served_citations)
    markers = cited_markers(text)
    if not markers:
        return 1.0 if not served else 0.0
    return sum(1 for m in markers if m in served) / len(markers)


def mean(values: Iterable[float | None]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


__all__ = ["citation_faithfulness", "cited_markers", "mean", "ndcg_at_k", "recall_at_k"]
