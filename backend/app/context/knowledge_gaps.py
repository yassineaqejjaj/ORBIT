"""Knowledge gaps: what agents and people keep asking for that the project's memory cannot answer.

Pure (no I/O). Each context request records which sub-topics no served item covered. A topic missing once is
noise; one missing again and again, for different askers, is a hole in the project's knowledge. This module
groups the missing sub-topics by what they are about (stemmed key terms: « rétention des données » joins
« durée de rétention des données »), counts them and tells whether they are getting more or less frequent.

Only the *topic* is kept — never the full task text — so one person's question is not exposed to another.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.context.textutils import key_terms

KEY_TERMS = 6
MERGE_OVERLAP = 0.8

Trend = Literal["rising", "steady", "fading"]
Severity = Literal["critical", "recurring", "isolated"]


@dataclass(frozen=True, slots=True)
class MissingTopic:
    topic: str
    at: datetime
    asker: str | None  # user or agent identifier; only used to count distinct askers
    score: float


def topic_key(topic: str) -> str:
    """Stable identity of a topic: its most telling stemmed terms, order-independent."""
    terms = sorted(key_terms(topic)[:KEY_TERMS])
    return " ".join(terms)


def severity(requests: int, askers: int) -> Severity:
    if requests >= 5 or askers >= 3:
        return "critical"
    return "recurring" if requests >= 2 else "isolated"


def trend(times: list[datetime], now: datetime, window_days: int) -> Trend:
    """Compare the second half of the window with the first half; needs a clear difference to say more."""
    middle = now - timedelta(days=window_days / 2)
    recent = sum(1 for t in times if t >= middle)
    older = len(times) - recent
    if recent >= 2 * max(older, 1) and recent >= 2:
        return "rising"
    if older >= 2 * max(recent, 1) and older >= 2:
        return "fading"
    return "steady"


def _terms(topic: str) -> frozenset[str]:
    return frozenset(key_terms(topic)[:KEY_TERMS])


def _same_topic(a: frozenset[str], b: frozenset[str]) -> bool:
    """One topic when the shorter wording is (almost) contained in the longer, on at least two terms."""
    shared = len(a & b)
    if not shared:
        return False
    if len(a) == 1 or len(b) == 1:
        return a == b
    return shared >= 2 and shared / min(len(a), len(b)) >= MERGE_OVERLAP


def aggregate(items: list[MissingTopic], now: datetime, window_days: int) -> list[dict]:
    """Gaps ordered by how often they came up, then how recently."""
    clusters: list[tuple[frozenset[str], list[MissingTopic]]] = []
    for item in sorted(items, key=lambda i: -len(_terms(i.topic))):  # the fullest wording names the cluster
        terms = _terms(item.topic)
        if not terms:
            continue
        for known, members in clusters:
            if _same_topic(terms, known):
                members.append(item)
                break
        else:
            clusters.append((terms, [item]))
    gaps = []
    for terms, members in clusters:
        askers = {m.asker for m in members if m.asker}
        wording = Counter(m.topic.strip() for m in members).most_common(1)[0][0]
        times = [m.at for m in members]
        gaps.append(
            {
                "key": " ".join(sorted(terms)),
                "topic": wording,
                "requests": len(members),
                "askers": len(askers),
                "first_seen": min(times),
                "last_seen": max(times),
                "avg_score": round(sum(m.score for m in members) / len(members), 2),
                "trend": trend(times, now, window_days),
                "severity": severity(len(members), len(askers)),
            }
        )
    gaps.sort(key=lambda g: (-g["requests"], -g["last_seen"].timestamp(), g["key"]))
    return gaps
