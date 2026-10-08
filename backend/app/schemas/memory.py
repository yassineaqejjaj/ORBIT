"""Memory items, provenance, history, relations and the memory graph."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.enums import (
    ActorType,
    AgentKind,
    Intent,
    MemoryEventType,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    RelationNodeType,
    RelationType,
)
from app.schemas.common import AclPrincipals, ApiModel, ClassificationLevel, InputModel, Tags


class MemoryItem(ApiModel):
    id: uuid.UUID
    lineage_id: uuid.UUID
    version: int
    is_current: bool
    scope: MemoryScope
    kind: MemoryKind
    status: MemoryStatus
    title: str
    content: str
    confidence: float
    classification: int
    acl_principals: list[str]
    tags: list[str]
    subject_user_id: uuid.UUID | None
    session_id: str | None
    expires_at: datetime | None
    valid_from: datetime
    valid_to: datetime | None
    supersedes_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None
    created_by_type: ActorType
    created_by_id: uuid.UUID | None
    rationale: str | None = None
    decided_by: str | None = None
    confidence_reason: str | None = None
    skill_meta: dict[str, Any] | None = None
    created_by_label: str = ""
    provenance_count: int = 0
    created_at: datetime
    updated_at: datetime


class Provenance(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID | None
    document_title: str | None = None
    chunk_id: uuid.UUID | None
    context_request_id: uuid.UUID | None
    source_label: str
    excerpt: str
    created_at: datetime


class MemoryEvent(ApiModel):
    id: uuid.UUID
    memory_item_id: uuid.UUID
    event: MemoryEventType
    actor_type: ActorType
    actor_id: uuid.UUID | None
    actor_label: str = ""
    reason: str | None
    data: dict[str, Any]
    created_at: datetime


class Relation(ApiModel):
    id: uuid.UUID
    rel_type: RelationType
    direction: Literal["out", "in"]
    other_type: RelationNodeType
    other_id: uuid.UUID
    other_title: str | None = None
    confidence: float
    detail: str | None
    method: str | None = None
    score: float | None = None
    explanation: str | None = None
    created_at: datetime


class MemoryDetail(ApiModel):
    item: MemoryItem
    provenance: list[Provenance]
    history: list[MemoryEvent]
    versions: list[MemoryItem]
    relations: list[Relation]


class ProvenanceIn(InputModel):
    document_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    excerpt: str | None = Field(default=None, max_length=4000)
    source_label: str | None = Field(default=None, max_length=300)


class SkillMetaIn(InputModel):
    """§D1 procedure metadata (Agent Skills ``SKILL.md`` front matter + injection rules)."""

    name: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=1024)
    task_types: list[Intent] = Field(default_factory=list, max_length=10)
    agent_kinds: list[AgentKind] = Field(default_factory=list, max_length=10)


class MemoryIn(InputModel):
    scope: MemoryScope
    kind: MemoryKind
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20000)
    classification: ClassificationLevel | None = None
    acl_principals: AclPrincipals | None = None
    tags: Tags | None = None
    subject_user_id: uuid.UUID | None = None
    session_id: str | None = Field(default=None, max_length=200)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    supersedes_id: uuid.UUID | None = None
    status: Literal["proposed", "validated"] | None = None
    provenance: list[ProvenanceIn] | None = Field(default=None, max_length=50)
    skill_meta: SkillMetaIn | None = None


class MemoryUpdateIn(InputModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    tags: Tags | None = None
    valid_to: datetime | None = None
    classification: ClassificationLevel | None = None
    kind: MemoryKind | None = None
    skill_meta: SkillMetaIn | None = None


class ReasonIn(InputModel):
    reason: str | None = Field(default=None, max_length=2000)


class ReasonRequiredIn(InputModel):
    reason: str = Field(min_length=1, max_length=2000)


class SupersedeIn(InputModel):
    by_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=2000)


class GraphNode(ApiModel):
    id: str
    type: str
    label: str
    kind: str | None = None
    status: str | None = None


class GraphEdge(ApiModel):
    source: str
    target: str
    rel_type: RelationType
    confidence: float | None = None
    detail: str | None = None
    method: str | None = None


class MemoryGraph(ApiModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class Skill(ApiModel):
    """§D1 procedure served as an Agent Skill."""

    name: str
    description: str
    task_types: list[str]
    agent_kinds: list[str]
    title: str
    memory_id: uuid.UUID
    lineage_id: uuid.UUID
    version: int
    status: MemoryStatus
    classification: int
    updated_at: datetime


class SkillDetail(Skill):
    skill_md: str


class EntityAliasOut(ApiModel):
    alias: str
    merged_from_id: uuid.UUID | None = None


class EntityOut(ApiModel):
    """§D2 resolved entity and its surface forms."""

    id: uuid.UUID
    name: str
    kind: str
    merged_into_id: uuid.UUID | None
    aliases: list[EntityAliasOut]
    created_at: datetime


class EntityIn(InputModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="concept", max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=30)


class EntityMergeIn(InputModel):
    source_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=2000)


class EntitySuggestion(ApiModel):
    a: EntityOut
    b: EntityOut
    score: float
    reason: str
