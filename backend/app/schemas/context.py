"""Context requests (``POST /projects/{slug}/context``), packages, decisions and feedback."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.enums import (
    CandidateType,
    FeedbackFlag,
    Intent,
    MemoryKind,
    MemoryScope,
    PrincipalKind,
    ReasonCode,
    SourceKind,
)
from app.schemas.agents import AgentRef
from app.schemas.common import ApiModel, ClassificationLevel, InputModel
from app.schemas.users import UserRef


class BaseSnapshotRef(InputModel):
    name: str = Field(min_length=1, max_length=120)
    version: int | None = Field(default=None, ge=1)


class SaveSnapshotRef(InputModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")


class ContextRequestIn(InputModel):
    task: str = Field(min_length=1, max_length=8000)
    intent: Intent | None = None
    agent_id: uuid.UUID | None = None
    on_behalf_of: uuid.UUID | None = None
    token_budget: int | None = Field(default=None, ge=500, le=32000)
    scopes: list[MemoryScope] | None = None
    source_kinds: list[SourceKind] | None = None
    include_sources: bool = True
    freshness_days: int | None = Field(default=None, ge=1, le=36500)
    max_classification: ClassificationLevel | None = None
    min_relevance: float | None = Field(default=None, ge=0, le=1)
    session_id: str | None = Field(default=None, max_length=200)
    base_snapshot: BaseSnapshotRef | None = None
    save_snapshot: SaveSnapshotRef | None = None
    explain: bool | None = Field(
        default=None, description="Défaut : true pour un humain, false pour un agent"
    )
    mode: Literal["full", "progressive"] = Field(
        default="full",
        description="progressive : résumé + index (identifiants) ; détail via expand_source, get_decision…",
    )
    cache_hints: bool = Field(
        default=False,
        description="Contexte découpé en blocs avec points d'arrêt cache_control (format Anthropic)",
    )
    as_of: datetime | None = Field(
        default=None,
        description="Mémoire « telle que connue au » : versions connues et valides à cette date (§D2)",
    )


class Scores(ApiModel):
    bm25: float | None = None
    dense: float | None = None
    rrf: float | None = None
    rerank: float | None = None
    freshness: float | None = None
    final: float = 0.0


class ContextItem(ApiModel):
    citation: str
    candidate_type: CandidateType
    id: str
    document_id: uuid.UUID | None = None
    memory_item_id: uuid.UUID | None = None
    title: str
    source_kind: SourceKind | None = None
    memory_kind: MemoryKind | None = None
    memory_scope: MemoryScope | None = None
    uri: str | None = None
    version: int | None = None
    excerpt: str
    tokens: int
    scores: Scores
    classification: int
    date: datetime | None = None
    pii_redacted: bool = False
    reason_code: ReasonCode
    reason_detail: str = ""


class ExcludedItem(ApiModel):
    candidate_type: CandidateType
    id: str | None = None
    title: str | None = None
    excerpt: str | None = None
    source_kind: SourceKind | None = None
    memory_kind: MemoryKind | None = None
    classification: int | None = None
    scores: Scores = Field(default_factory=Scores)
    reason_code: ReasonCode
    reason_detail: str = ""
    redacted: bool = False
    related_citation: str | None = None


class RetrievalQuery(ApiModel):
    text: str
    #: ``task``, ``multi``, ``hyde``, ``expansion`` or ``subtopic``.
    kind: str


class RetrievalRound(ApiModel):
    """One round of iterative retrieval (docs/AI_CONTEXT_ENGINEERING.md §B4)."""

    round: int
    queries: list[RetrievalQuery] = []
    #: New items (chunks + memory) found by this round.
    new_items: int = 0
    #: Sub-topics still uncovered after this round.
    uncovered: list[str] = []
    ms: float = 0


class ContextTimings(ApiModel):
    understand: float = 0
    rewrite: float = 0
    retrieve: float = 0
    fuse: float = 0
    rerank: float = 0
    govern: float = 0
    select: float = 0
    compress: float = 0
    package: float = 0
    total: float = 0
    #: Retrieval rounds (§B3 rewrites in round 1, §B4 targeted rounds), within ``retrieve``.
    rounds: list[RetrievalRound] = []


class ContextSnapshotInfo(ApiModel):
    id: uuid.UUID
    name: str
    version: int


class ContextConfig(ApiModel):
    retrieval: str = "hybrid-bm25-knn-rrf-v1"
    reranker: str
    embedding_model: str
    llm: str | None = None
    #: §C4 sentence compression: ``learned-embeddings-mmr`` (+ ``+pruner``) or ``extractive``.
    compression: str | None = None


class CacheControl(ApiModel):
    type: Literal["ephemeral"] = "ephemeral"


class CacheHintBlock(ApiModel):
    """One Anthropic Messages API text block; ``cache_control`` marks the end of the cacheable prefix."""

    type: Literal["text"] = "text"
    text: str
    cache_control: CacheControl | None = None


class ContextIndexEntry(ApiModel):
    """§C2 progressive mode: one served item and how to expand it."""

    citation: str
    id: str
    candidate_type: CandidateType
    title: str
    memory_kind: MemoryKind | None = None
    #: MCP tool returning the detail (``expand_source``, ``get_decision``, ``get_memory_item``).
    tool: str
    #: Tokens of the full item text (what expanding costs).
    tokens_full: int


class ContextSufficiency(ApiModel):
    """§C5: is the served context enough to answer the task?"""

    score: float
    verdict: Literal["sufficient", "partial", "insufficient"]
    #: Sub-topics (chantier B decomposition, or the task itself) no served item covers.
    missing_subtopics: list[str] = Field(default_factory=list)
    covered_subtopics: list[str] = Field(default_factory=list)
    explanation: str = ""


class AppliedProfile(ApiModel):
    """§C3 context profile of the requesting agent's kind, as applied to this package."""

    kind: str
    sections: list[str]
    token_budget: int | None = None
    min_relevance: float | None = None
    sufficient_threshold: float | None = None
    customized: bool = False


class ContextPackage(ApiModel):
    request_id: uuid.UUID
    trace_id: str
    task: str
    intent: Intent
    created_at: datetime
    context: str
    items: list[ContextItem]
    excluded: list[ExcludedItem]
    exclusion_summary: dict[ReasonCode, int]
    tokens_used: int
    token_budget: int
    candidates_count: int
    timings: ContextTimings
    snapshot: ContextSnapshotInfo | None = None
    config: ContextConfig
    warnings: list[str] = Field(default_factory=list)
    #: §C1: SHA-256 of the stable prefix of ``context`` and its size; ``cache_prefix_reused`` when a
    #: request of this project served the same prefix within ``ORBIT_CONTEXT_CACHE_TTL_SECONDS``.
    cache_prefix_hash: str | None = None
    cache_prefix_tokens: int = 0
    cache_prefix_reused: bool = False
    cache_hints: list[CacheHintBlock] | None = None
    mode: Literal["full", "progressive"] = "full"
    index: list[ContextIndexEntry] = Field(default_factory=list)
    profile: AppliedProfile | None = None
    sufficiency: ContextSufficiency | None = None


class ItemFlag(InputModel):
    citation: str = Field(min_length=1, max_length=16)
    flag: FeedbackFlag


class FeedbackIn(InputModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)
    item_flags: list[ItemFlag] | None = Field(default=None, max_length=100)


class ItemFlagView(ApiModel):
    citation: str
    flag: FeedbackFlag


class ContextFeedback(ApiModel):
    id: uuid.UUID
    actor_type: PrincipalKind
    actor_id: uuid.UUID | None
    rating: int
    comment: str | None
    item_flags: list[ItemFlagView]
    created_at: datetime


class ContextRequestDetail(ContextPackage):
    feedback: list[ContextFeedback] = Field(default_factory=list)


class SnapshotRef(ApiModel):
    name: str
    version: int


class ContextRequestSummary(ApiModel):
    id: uuid.UUID
    trace_id: str
    task: str
    intent: Intent
    agent: AgentRef | None
    user: UserRef | None
    latency_ms: int
    tokens_used: int
    token_budget: int
    included_count: int
    excluded_count: int
    candidates_count: int
    snapshot: SnapshotRef | None
    rating: float | None
    created_at: datetime


ProfileSection = Literal[
    "decisions", "requirements", "constraints", "facts", "preferences", "sources", "session"
]


class ContextProfileIn(InputModel):
    """§C3 editable profile of one agent kind (``null`` = project default)."""

    sections: list[ProfileSection] = Field(min_length=1, max_length=7)
    token_budget: int | None = Field(default=None, ge=500, le=32000)
    min_relevance: float | None = Field(default=None, ge=0, le=1)
    sufficient_threshold: float | None = Field(default=None, ge=0, le=1)


class ProfileSuggestion(ApiModel):
    kind: str
    feedback_count: int
    avg_rating: float | None = None
    #: Suggested values (``token_budget``, ``min_relevance``, ``sections``); empty = no change.
    changes: dict[str, Any] = Field(default_factory=dict)
    rationale: list[str] = Field(default_factory=list)


class ContextProfileView(AppliedProfile):
    default: AppliedProfile
    suggestion: ProfileSuggestion
