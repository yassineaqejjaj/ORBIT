"""Governance policy (ARCHITECTURE §9.5, §3, §4).

For each retrieval candidate, rules are evaluated in ``app.enums.GOVERNANCE_ORDER``
(FORGOTTEN → ACL → CLASSIFICATION → SCOPE → EXPIRED → STALE → SUPERSEDED → LOW_SCORE); the first
blocking rule gives the exclusion ``ReasonCode`` and a French ``reason_detail`` in the style of the §4
table (« C3 > habilitation C1 », « 214 j > 180 j (tickets) », « score 0,21 < seuil 0,35 »…).

Non-leak principle (§3): verdicts carry a ``redact`` flag. ``EXCLUDED_ACL`` /
``EXCLUDED_CLASSIFICATION`` (and the exclusion of another user's personal memory) are persisted in
full but returned without id, title nor excerpt to callers who could not access the content
themselves; agents only receive counters.

Candidates are always hydrated from Postgres (source of truth for status, ACL, classification,
dates and supersession) before being evaluated — never from the search index payload alone.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.enums import (
    GOVERNANCE_ORDER,
    MEMORY_KIND_LABELS,
    SOURCE_KIND_LABELS,
    CandidateType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    ReasonCode,
    SourceKind,
    classification_code,
)
from app.governance import freshness
from app.governance.acl import PROJECT_ALL, acl_allows, user_principal

FORGOTTEN_STATUS = "forgotten"
SUPERSEDED_STATUS = "superseded"
OBSOLETE_STATUS = "obsolete"

MEMORY_SCOPE_LABELS: dict[MemoryScope, str] = {
    MemoryScope.short_term: "court terme",
    MemoryScope.project: "projet",
    MemoryScope.user: "utilisateur",
    MemoryScope.long_term: "long terme",
}

#: Grammatical gender of memory kind labels (for « décision validée » / « besoin validé »).
_FEMININE_KINDS: frozenset[MemoryKind] = frozenset(
    {MemoryKind.decision, MemoryKind.constraint, MemoryKind.preference, MemoryKind.summary}
)

_ACL_ENTRY_LABELS: dict[str, str] = {
    PROJECT_ALL: "tous les membres",
    "role:owner": "propriétaires",
    "role:editor": "éditeurs",
    "role:viewer": "lecteurs",
}


# --- Data structures ------------------------------------------------------------------------------


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
    include_sources: bool = True


@dataclass(slots=True)
class ScoreBreakdown:
    """Retrieval and reranking signals of a candidate (all in ``[0, 1]`` except BM25/ranks)."""

    bm25: float | None = None
    bm25_rank: int | None = None
    dense: float | None = None
    dense_rank: int | None = None
    rrf: float | None = None
    rrf_norm: float = 0.0
    cross_encoder: float | None = None
    rerank: float | None = None
    freshness: float | None = None
    type_boost: float = 0.0
    term_overlap: float = 0.0
    final: float = 0.0


@dataclass(frozen=True, slots=True)
class SupersessionInfo:
    """The newer item/version that replaces a candidate."""

    title: str
    version: int | None
    date: datetime | None


@dataclass(frozen=True, slots=True)
class ForgetInfo:
    at: datetime | None
    by: str | None


@dataclass(slots=True)
class Candidate:
    """Normalised retrieval candidate (chunk, memory item or session turn), hydrated from Postgres."""

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
    memory_kind: MemoryKind | None = None
    subject_user_id: uuid.UUID | None = None
    session_id: str | None = None
    expires_at: datetime | None = None
    valid_to: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    #: Stable identity across versions: ``chunk:<id>``, ``memory:<lineage_id>``, ``session:<id>``.
    key: str = ""
    lineage_id: uuid.UUID | None = None
    version: int | None = None
    uri: str | None = None
    section: str | None = None
    confidence: float = 1.0
    #: Additional ACLs that must *all* be satisfied (e.g. the parent document's ACL for a chunk).
    extra_acls: list[list[str]] = field(default_factory=list)
    is_org_memory: bool = False
    pii_redacted: bool = False
    pinned: bool = False
    pinned_label: str | None = None
    superseded_by: SupersessionInfo | None = None
    forgotten: ForgetInfo | None = None
    status_changed_at: datetime | None = None
    embedding: list[float] | None = None
    tokens: int = 0
    scores: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    retrieved_by: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.key:
            self.key = candidate_key(self.candidate_type, self.id, self.lineage_id)

    @property
    def is_forgotten(self) -> bool:
        return self.status == FORGOTTEN_STATUS

    @property
    def is_validated(self) -> bool:
        return self.status == MemoryStatus.validated.value

    @property
    def all_acls(self) -> list[list[str]]:
        return [self.acl_principals, *self.extra_acls]


@dataclass(frozen=True, slots=True)
class Verdict:
    reason_code: ReasonCode
    reason_detail: str
    redact: bool = False

    @property
    def included(self) -> bool:
        return self.reason_code.is_included


def candidate_key(candidate_type: CandidateType | str, item_id: str, lineage_id: uuid.UUID | None) -> str:
    kind = str(getattr(candidate_type, "value", candidate_type))
    if kind == CandidateType.memory.value and lineage_id is not None:
        return f"memory:{lineage_id}"
    return f"{kind}:{item_id}"


# --- Formatting helpers ---------------------------------------------------------------------------


def format_score(value: float) -> str:
    """French decimal formatting used in reason details: ``0.8213 -> "0,82"``."""
    return f"{value:.2f}".replace(".", ",")


def format_score_floor(value: float) -> str:
    """Like :func:`format_score` but rounded down (« 0,34 < seuil 0,35 » never reads « 0,35 < 0,35 »)."""
    return format_score(math.floor(max(value, 0.0) * 100) / 100)


def format_date_fr(value: datetime | None) -> str:
    """``12/09/2026``."""
    return freshness.as_aware(value).strftime("%d/%m/%Y") if value else ""


def format_date_iso(value: datetime | None) -> str:
    """``2026-09-12``."""
    return freshness.as_aware(value).strftime("%Y-%m-%d") if value else ""


def memory_status_label(kind: MemoryKind | None, status: str) -> str:
    feminine = kind in _FEMININE_KINDS
    labels = {
        MemoryStatus.validated.value: "validée" if feminine else "validé",
        MemoryStatus.proposed.value: "proposée" if feminine else "proposé",
        MemoryStatus.superseded.value: "remplacée" if feminine else "remplacé",
        MemoryStatus.obsolete.value: "obsolète",
        MemoryStatus.forgotten.value: "oubliée" if feminine else "oublié",
    }
    return labels.get(status, status)


def candidate_type_label(candidate: Candidate) -> str:
    """« décision validée », « extrait (ticket) », « tour de session »."""
    if candidate.candidate_type == CandidateType.memory:
        kind_label = MEMORY_KIND_LABELS.get(candidate.memory_kind, "mémoire") if candidate.memory_kind else "mémoire"
        label = f"{kind_label.lower()} {memory_status_label(candidate.memory_kind, candidate.status)}"
        if candidate.is_org_memory:
            label += " · organisation"
        return label
    if candidate.candidate_type == CandidateType.session:
        return "tour de session"
    kind = SOURCE_KIND_LABELS.get(candidate.source_kind, "source") if candidate.source_kind else "source"
    return f"extrait ({kind.lower()})"


def acl_label(entries: list[str]) -> str:
    labels = []
    for entry in entries:
        if entry.startswith("user:"):
            label = "utilisateur désigné"
        else:
            label = _ACL_ENTRY_LABELS.get(entry, entry)
        if label not in labels:
            labels.append(label)
    return ", ".join(labels) if labels else "aucun principal"


def supersession_detail(info: SupersessionInfo | None) -> str:
    if info is None:
        return "remplacé par une version plus récente"
    parts = [f"v{info.version}"] if info.version is not None else []
    if info.date is not None:
        parts.append(format_date_iso(info.date))
    suffix = f" ({', '.join(parts)})" if parts else ""
    return f"remplacé par “{info.title}”{suffix}"


# --- Rules ----------------------------------------------------------------------------------------

Rule = Callable[[Candidate, GovernanceContext], Verdict | None]


def _rule_forgotten(c: Candidate, ctx: GovernanceContext) -> Verdict | None:
    if not c.is_forgotten:
        return None
    detail = "oublié"
    if c.forgotten is not None:
        if c.forgotten.at is not None:
            detail += f" le {format_date_fr(c.forgotten.at)}"
        if c.forgotten.by:
            detail += f" par {c.forgotten.by}"
    return Verdict(ReasonCode.EXCLUDED_FORGOTTEN, detail)


def _is_subject_only_acl(c: Candidate) -> bool:
    """Personal memory restricted to its subject: privacy is handled (and explained) by SCOPE."""
    if c.memory_scope != MemoryScope.user or c.subject_user_id is None:
        return False
    subject = user_principal(c.subject_user_id)
    return bool(c.acl_principals) and all(entry == subject for entry in c.acl_principals)


def _rule_acl(c: Candidate, ctx: GovernanceContext) -> Verdict | None:
    for index, acl in enumerate(c.all_acls):
        if acl_allows(acl, ctx.principals):
            continue
        if index == 0 and _is_subject_only_acl(c):
            continue
        return Verdict(ReasonCode.EXCLUDED_ACL, f"réservé à : {acl_label(list(acl or []))}", redact=True)
    return None


def _rule_classification(c: Candidate, ctx: GovernanceContext) -> Verdict | None:
    if int(c.classification) <= int(ctx.clearance):
        return None
    detail = f"{classification_code(c.classification)} > habilitation {classification_code(ctx.clearance)}"
    return Verdict(ReasonCode.EXCLUDED_CLASSIFICATION, detail, redact=True)


def _rule_scope(c: Candidate, ctx: GovernanceContext) -> Verdict | None:
    if c.candidate_type == CandidateType.memory:
        scope = c.memory_scope or MemoryScope.project
        # Another user's personal memory is never described to the caller (non-leak).
        private = scope == MemoryScope.user and (
            ctx.requester_user_id is None or c.subject_user_id != ctx.requester_user_id
        )
        if scope not in ctx.scopes:
            return Verdict(
                ReasonCode.EXCLUDED_SCOPE,
                f"portée non demandée (mémoire {MEMORY_SCOPE_LABELS[scope]})",
                redact=private,
            )
        if scope == MemoryScope.user:
            if ctx.requester_user_id is None:
                return Verdict(
                    ReasonCode.EXCLUDED_SCOPE,
                    "mémoire utilisateur (aucun utilisateur représenté)",
                    redact=True,
                )
            if c.subject_user_id != ctx.requester_user_id:
                return Verdict(
                    ReasonCode.EXCLUDED_SCOPE, "mémoire utilisateur d'un autre utilisateur", redact=True
                )
        return None
    if c.candidate_type == CandidateType.chunk:
        if not ctx.include_sources:
            return Verdict(ReasonCode.EXCLUDED_SCOPE, "extraits de sources non demandés")
        if ctx.source_kinds is not None and c.source_kind not in ctx.source_kinds:
            return Verdict(
                ReasonCode.EXCLUDED_SCOPE,
                f"type de source non demandé ({freshness.kind_plural_label(c.source_kind)})",
            )
        return None
    if MemoryScope.short_term not in ctx.scopes:
        return Verdict(ReasonCode.EXCLUDED_SCOPE, "portée non demandée (session en cours)")
    return None


def _rule_expired(c: Candidate, ctx: GovernanceContext) -> Verdict | None:
    if c.candidate_type != CandidateType.memory or c.memory_scope != MemoryScope.short_term:
        return None
    if c.expires_at is None or freshness.as_aware(c.expires_at) > freshness.as_aware(ctx.now):
        return None
    return Verdict(ReasonCode.EXCLUDED_EXPIRED, f"expirée le {format_date_fr(c.expires_at)}")


def _memory_is_durable(c: Candidate) -> bool:
    """Memory that stays in force until superseded (never excluded for age)."""
    if c.memory_scope in (MemoryScope.long_term, MemoryScope.user, MemoryScope.short_term):
        return True
    return c.is_validated and c.memory_kind in (MemoryKind.decision, MemoryKind.constraint)


def _rule_stale(c: Candidate, ctx: GovernanceContext) -> Verdict | None:
    if c.pinned or c.candidate_type == CandidateType.session:
        return None
    if c.candidate_type == CandidateType.memory:
        if c.valid_to is not None and freshness.as_aware(c.valid_to) <= freshness.as_aware(ctx.now):
            return Verdict(ReasonCode.EXCLUDED_STALE, f"validité échue le {format_date_iso(c.valid_to)}")
        if _memory_is_durable(c) or ctx.freshness_override_days is None:
            return None
        limit = int(ctx.freshness_override_days)
        age = freshness.whole_days(c.date, ctx.now)
        if age is not None and age > limit:
            return Verdict(ReasonCode.EXCLUDED_STALE, f"{age} j > {limit} j (demandé)")
        return None
    limit_days = freshness.policy_days(c.source_kind, ctx.freshness_days, ctx.freshness_override_days)
    if limit_days is None:
        return None
    age = freshness.whole_days(c.date, ctx.now)
    if age is None or age <= limit_days:
        return None
    label = "demandé" if ctx.freshness_override_days is not None else freshness.kind_plural_label(c.source_kind)
    return Verdict(ReasonCode.EXCLUDED_STALE, f"{age} j > {limit_days} j ({label})")


def _rule_superseded(c: Candidate, ctx: GovernanceContext) -> Verdict | None:
    if c.status == SUPERSEDED_STATUS:
        return Verdict(ReasonCode.EXCLUDED_SUPERSEDED, supersession_detail(c.superseded_by))
    if c.candidate_type == CandidateType.memory and c.status == OBSOLETE_STATUS:
        detail = "marqué obsolète"
        if c.status_changed_at is not None:
            detail += f" le {format_date_iso(c.status_changed_at)}"
        return Verdict(ReasonCode.EXCLUDED_SUPERSEDED, detail)
    return None


def _rule_low_score(c: Candidate, ctx: GovernanceContext) -> Verdict | None:
    if c.pinned or c.candidate_type == CandidateType.session:
        return None
    if c.score >= ctx.min_relevance:
        return None
    return Verdict(
        ReasonCode.EXCLUDED_LOW_SCORE,
        f"score {format_score_floor(c.score)} < seuil {format_score(ctx.min_relevance)}",
    )


RULES: dict[ReasonCode, Rule] = {
    ReasonCode.EXCLUDED_FORGOTTEN: _rule_forgotten,
    ReasonCode.EXCLUDED_ACL: _rule_acl,
    ReasonCode.EXCLUDED_CLASSIFICATION: _rule_classification,
    ReasonCode.EXCLUDED_SCOPE: _rule_scope,
    ReasonCode.EXCLUDED_EXPIRED: _rule_expired,
    ReasonCode.EXCLUDED_STALE: _rule_stale,
    ReasonCode.EXCLUDED_SUPERSEDED: _rule_superseded,
    ReasonCode.EXCLUDED_LOW_SCORE: _rule_low_score,
}

assert tuple(RULES) == GOVERNANCE_ORDER, "governance rules must follow GOVERNANCE_ORDER"


def evaluate(candidate: Candidate, ctx: GovernanceContext) -> Verdict | None:
    """Return the first blocking :class:`Verdict`, or ``None`` when the candidate may be selected."""
    for code in GOVERNANCE_ORDER:
        verdict = RULES[code](candidate, ctx)
        if verdict is not None:
            return verdict
    return None


def included_verdict(candidate: Candidate, now: datetime) -> Verdict:
    """``INCLUDED_PINNED`` (« snapshot spec-atlas@v2 ») or ``INCLUDED_RELEVANT``
    (« score 0,82 · décision validée · 12 j »)."""
    if candidate.pinned:
        return Verdict(ReasonCode.INCLUDED_PINNED, f"snapshot {candidate.pinned_label or ''}".strip())
    parts = [f"score {format_score(candidate.score)}", candidate_type_label(candidate)]
    age = freshness.format_age(candidate.date, now)
    if age:
        parts.append(age)
    return Verdict(ReasonCode.INCLUDED_RELEVANT, " · ".join(parts))
