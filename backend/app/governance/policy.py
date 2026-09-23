"""Governance policy (interface — implemented by the context/governance teammate). ARCHITECTURE §9.5.

For each retrieval candidate, rules are evaluated in ``app.enums.GOVERNANCE_ORDER``
(FORGOTTEN → ACL → CLASSIFICATION → SCOPE → EXPIRED → STALE → SUPERSEDED → LOW_SCORE); the first
blocking rule gives the exclusion ``ReasonCode`` and a French ``reason_detail`` as specified in §4
(e.g. « C3 > habilitation C1 », « 214 j > 180 j (tickets) », « score 0,21 < seuil 0,35 »).

Non-leak principle (§3): ``EXCLUDED_ACL`` / ``EXCLUDED_CLASSIFICATION`` decisions are persisted in full
but must be returned with ``redacted=True`` (no id, title, excerpt) to callers without access; agents
only receive counters.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.enums import CandidateType, MemoryScope, ReasonCode, SourceKind


@dataclass(slots=True)
class GovernanceContext:
    """Everything the rules need about the request and the caller."""

    project_id: uuid.UUID
    principals: set[str]
    clearance: int
    requester_user_id: uuid.UUID | None
    session_id: str | None
    scopes: set[MemoryScope]
    source_kinds: set[SourceKind] | None
    freshness_days: Mapping[str, int]
    freshness_override_days: int | None
    min_relevance: float
    now: datetime


@dataclass(slots=True)
class Candidate:
    """Normalised retrieval candidate (chunk, memory item or session turn)."""

    candidate_type: CandidateType
    id: str
    title: str
    text: str
    classification: int
    acl_principals: list[str]
    status: str
    date: datetime | None
    score: float = 0.0
    source_kind: SourceKind | None = None
    document_id: uuid.UUID | None = None
    memory_item_id: uuid.UUID | None = None
    memory_scope: MemoryScope | None = None
    memory_kind: str | None = None
    subject_user_id: uuid.UUID | None = None
    session_id: str | None = None
    expires_at: datetime | None = None
    valid_to: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Verdict:
    reason_code: ReasonCode
    reason_detail: str

    @property
    def included(self) -> bool:
        return self.reason_code.is_included


def evaluate(candidate: Candidate, ctx: GovernanceContext) -> Verdict | None:
    """Return the first blocking :class:`Verdict`, or ``None`` when the candidate may be selected."""
    raise NotImplementedError("Moteur de gouvernance non implémenté")


def format_score(value: float) -> str:
    """French decimal formatting used in reason details: ``0.8213 -> "0,82"``."""
    return f"{value:.2f}".replace(".", ",")
