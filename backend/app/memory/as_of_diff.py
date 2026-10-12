"""What the project knew on one date versus another.

Pure (no I/O). The API reads the memory known (``as_of``) at two dates, already filtered to what the caller
may see; this module says what appeared, what went away (and why, when recorded) and what was rewritten.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Why = Literal["replaced", "obsolete", "expired", "forgotten", "unknown"]


@dataclass(frozen=True, slots=True)
class Known:
    """One lineage as it stood at a date."""

    id: uuid.UUID
    lineage_id: uuid.UUID
    version: int
    title: str
    content: str


@dataclass(frozen=True, slots=True)
class Latest:
    """The lineage's latest recorded state, used to explain why something is gone."""

    status: str
    valid_to: datetime | None
    superseded_by_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class Removal:
    before: Known
    why: Why
    replaced_by: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class Change:
    before: Known
    after: Known


@dataclass(frozen=True, slots=True)
class Diff:
    added: list[Known]
    removed: list[Removal]
    changed: list[Change]


def explain(latest: Latest | None, at: datetime) -> Why:
    """Why a lineage known at the first date is not known at the second."""
    if latest is None:
        return "unknown"
    if latest.superseded_by_id is not None or latest.status == "superseded":
        return "replaced"
    if latest.status == "obsolete":
        return "obsolete"
    if latest.status == "forgotten":
        return "forgotten"
    if latest.valid_to is not None and latest.valid_to <= at:
        return "expired"
    return "unknown"


def diff_known(
    before: list[Known], after: list[Known], latest: dict[uuid.UUID, Latest], at: datetime
) -> Diff:
    """Compare two snapshots of what was known, lineage by lineage."""
    old = {k.lineage_id: k for k in before}
    new = {k.lineage_id: k for k in after}
    added = sorted((k for lid, k in new.items() if lid not in old), key=lambda k: k.title.lower())
    changed = [
        Change(old[lid], new[lid])
        for lid in old.keys() & new.keys()
        if old[lid].id != new[lid].id
        and (old[lid].title, old[lid].content) != (new[lid].title, new[lid].content)
    ]
    changed.sort(key=lambda c: c.after.title.lower())
    removed: list[Removal] = []
    for lid, known in old.items():
        if lid in new:
            continue
        state = latest.get(lid)
        replacement = state.superseded_by_id if state else None
        removed.append(Removal(known, explain(state, at), replacement))
    removed.sort(key=lambda r: r.before.title.lower())
    return Diff(added, removed, changed)
