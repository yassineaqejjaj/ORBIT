"""Contradiction map: which things the project's memory says that cannot all be true.

Pure (no I/O). Takes the memory items a caller may see and the ``contradicts`` relations among them, and
groups them into clusters (connected components) ranked by how much they matter:

* ``critical`` — two *validated* items contradict each other: the team's own truth disagrees with itself;
* ``review`` — at least one side is still only *proposed*: a reviewer can settle it;
* ``minor`` — the contradiction is weak (score below :data:`MINOR_SCORE`) and involves no validated pair.

Only items the caller can see are ever passed in, so a contradiction with something restricted does not
appear (not even as a count): its existence would reveal that the restricted item exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.enums import MemoryStatus
from app.memory.conflicts import reliability_key

#: Contradictions are only worth a reviewer's time while both sides are live.
LIVE_STATUSES = (MemoryStatus.proposed, MemoryStatus.validated)
MINOR_SCORE = 0.5

Severity = Literal["critical", "review", "minor"]
_RANK: dict[str, int] = {"critical": 0, "review": 1, "minor": 2}


@dataclass(frozen=True, slots=True)
class MapItem:
    id: str
    title: str
    kind: str
    status: MemoryStatus
    classification: int
    confidence: float
    valid_from: datetime


@dataclass(frozen=True, slots=True)
class MapEdge:
    a: str
    b: str
    score: float | None
    method: str | None
    explanation: str | None


def _components(ids: list[str], edges: list[MapEdge]) -> list[list[str]]:
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for edge in edges:
        parent[find(edge.a)] = find(edge.b)
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def severity_of(items: dict[str, MapItem], edges: list[MapEdge]) -> Severity:
    if any(
        items[e.a].status == MemoryStatus.validated and items[e.b].status == MemoryStatus.validated
        for e in edges
    ):
        return "critical"
    if all((e.score or 0.0) < MINOR_SCORE for e in edges) and not any(
        items[e.a].status == MemoryStatus.proposed or items[e.b].status == MemoryStatus.proposed
        for e in edges
    ):
        return "minor"
    return "review"


def build_clusters(items: list[MapItem], edges: list[MapEdge]) -> list[dict]:
    """Clusters of mutually contradicting items, most severe first. Edges to unknown items are ignored."""
    by_id = {i.id: i for i in items if MemoryStatus(i.status) in LIVE_STATUSES}
    usable: list[MapEdge] = []
    seen: set[frozenset[str]] = set()
    for edge in edges:
        key = frozenset((edge.a, edge.b))
        if edge.a == edge.b or edge.a not in by_id or edge.b not in by_id or key in seen:
            continue
        seen.add(key)
        usable.append(edge)
    involved = sorted({e.a for e in usable} | {e.b for e in usable})
    clusters = []
    for members in _components(involved, usable):
        member_set = set(members)
        cluster_edges = [e for e in usable if e.a in member_set]
        severity = severity_of(by_id, cluster_edges)
        ranked = sorted((by_id[m] for m in members), key=reliability_key, reverse=True)
        clusters.append(
            {
                "severity": severity,
                "item_ids": [i.id for i in ranked],
                "suggested_keep": ranked[0].id,  # most reliable: validated > proposed, newer, more confident
                "max_classification": max(i.classification for i in ranked),
                "edges": [
                    {"a": e.a, "b": e.b, "score": e.score, "method": e.method, "explanation": e.explanation}
                    for e in cluster_edges
                ],
            }
        )
    clusters.sort(key=lambda c: (_RANK[c["severity"]], -len(c["item_ids"]), c["item_ids"][0]))
    return clusters
