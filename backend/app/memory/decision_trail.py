"""Decision trail: the story behind a piece of memory, in one chronological timeline.

Pure (no I/O). The API gathers what the caller may see — the chain of items each one replaced, their history
events and the sources they were drawn from — and this module merges it into ordered entries. Nothing is
invented: every entry is a recorded event, a recorded source or a recorded replacement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

#: When two entries share a timestamp, the story reads source → creation → review → replacement.
KIND_ORDER: dict[str, int] = {
    "source": 0,
    "created": 1,
    "edited": 2,
    "conflict_detected": 3,
    "validated": 4,
    "restored": 5,
    "superseded": 6,
    "replaced_by": 7,
    "obsoleted": 8,
    "forgotten": 9,
}


@dataclass(frozen=True, slots=True)
class TrailEntry:
    at: datetime
    kind: str
    label: str
    detail: str = ""
    item_id: str | None = None
    document_id: str | None = None
    actor: str = ""

    def key(self) -> tuple[float, int, str]:
        return (self.at.timestamp(), KIND_ORDER.get(self.kind, 99), self.label)


def build_timeline(entries: list[TrailEntry]) -> list[TrailEntry]:
    """Oldest first; identical entries (same instant, kind, label, item) are listed once."""
    seen: set[tuple[float, str, str, str | None]] = set()
    unique: list[TrailEntry] = []
    for entry in sorted(entries, key=TrailEntry.key):
        marker = (entry.at.timestamp(), entry.kind, entry.label, entry.item_id)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(entry)
    return unique


def excerpt(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
