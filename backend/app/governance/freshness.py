"""Freshness: age computation, exponential decay score and per-source-kind freshness policies.

* The rerank freshness signal (ARCHITECTURE §9.4) is an exponential decay with a 90-day half-life:
  ``0.5 ** (age_days / 90)`` (1.0 for brand-new content, 0.5 after 90 days, 0.25 after 180 days).
* The ``STALE`` governance rule (§9.5) compares the age of a candidate with the project policy
  ``settings.freshness_days[source_kind]`` or with the request-wide override ``freshness_days``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime

from app.enums import SourceKind

HALF_LIFE_DAYS = 90.0
#: Neutral freshness when a candidate carries no business date.
UNKNOWN_FRESHNESS = 0.5
_SECONDS_PER_DAY = 86_400.0

#: Plural French labels used in ``EXCLUDED_STALE`` details (« 214 j > 180 j (tickets) »).
SOURCE_KIND_PLURAL_LABELS: dict[SourceKind, str] = {
    SourceKind.document: "documents",
    SourceKind.note: "notes",
    SourceKind.ticket: "tickets",
    SourceKind.crm: "fiches CRM",
    SourceKind.feedback: "retours clients",
    SourceKind.agent_trace: "traces d'agents",
    SourceKind.url: "pages web",
}


def as_aware(value: datetime) -> datetime:
    """Treat naive datetimes as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def age_days(date: datetime | None, now: datetime) -> float | None:
    """Age in (fractional) days, never negative; ``None`` when the date is unknown."""
    if date is None:
        return None
    delta = (as_aware(now) - as_aware(date)).total_seconds() / _SECONDS_PER_DAY
    return max(0.0, delta)


def whole_days(date: datetime | None, now: datetime) -> int | None:
    age = age_days(date, now)
    return None if age is None else math.floor(age)


def decay_score(date: datetime | None, now: datetime, half_life_days: float = HALF_LIFE_DAYS) -> float:
    """Exponential decay in ``[0, 1]`` (``UNKNOWN_FRESHNESS`` when the date is unknown)."""
    age = age_days(date, now)
    if age is None:
        return UNKNOWN_FRESHNESS
    if half_life_days <= 0:
        return 1.0
    return float(0.5 ** (age / half_life_days))


def policy_days(
    source_kind: SourceKind | str | None,
    project_policy: Mapping[str, int] | None,
    override_days: int | None = None,
) -> int | None:
    """Maximum age allowed for a source kind: the request override wins over the project policy."""
    if override_days is not None and override_days > 0:
        return int(override_days)
    if source_kind is None or not project_policy:
        return None
    value = project_policy.get(str(getattr(source_kind, "value", source_kind)))
    if value is None or int(value) <= 0:
        return None
    return int(value)


def kind_plural_label(source_kind: SourceKind | str | None) -> str:
    if source_kind is None:
        return "sources"
    try:
        return SOURCE_KIND_PLURAL_LABELS[SourceKind(source_kind)]
    except ValueError:
        return str(source_kind)


def format_days(days: float | int) -> str:
    """``214 -> "214 j"``."""
    return f"{math.floor(days)} j"


def format_age(date: datetime | None, now: datetime) -> str | None:
    """Human age used in inclusion details: « aujourd'hui », « 12 j »."""
    days = whole_days(date, now)
    if days is None:
        return None
    return "aujourd'hui" if days == 0 else format_days(days)
