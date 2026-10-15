"""Versioned, immutable context snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from app.enums import CandidateType, Intent, MemoryKind, SourceKind
from app.schemas.common import CONTEXT_SCHEMA_VERSION, ApiModel


class SnapshotGroup(ApiModel):
    """Entry of ``GET /snapshots``: one line per snapshot name."""

    name: str
    latest_version: int
    versions: int
    updated_at: datetime
    last_task: str


class SnapshotItem(ApiModel):
    key: str = Field(description='"chunk:<id>" | "memory:<lineage_id>"')
    citation: str
    candidate_type: CandidateType
    id: str
    title: str
    excerpt: str
    source_kind: SourceKind | None = None
    memory_kind: MemoryKind | None = None
    version: int | None = None
    forgotten: bool = False
    #: Classification (0-3) of the item; ``None`` for a reader who may not know it. Never below the
    #: item's current level. Snapshots stored before NOV-73 get it from the item's current state.
    classification: int | None = None


class SnapshotSummary(ApiModel):
    id: uuid.UUID
    name: str
    version: int
    parent_version: int | None = None
    task: str
    intent: Intent
    token_count: int
    items_count: int = 0
    content_hash: str
    created_by_label: str = ""
    created_at: datetime


class Snapshot(SnapshotSummary):
    #: Contract version (``CONTEXT_SCHEMA_VERSION``); additive changes only.
    schema_version: int = CONTEXT_SCHEMA_VERSION
    content: str
    items: list[SnapshotItem]
    request_id: uuid.UUID | None
    #: Highest classification (0-3) of the items delivered to this reader (hidden / forgotten ones excluded).
    max_classification: int = 0


class SnapshotDiff(ApiModel):
    model_config = ConfigDict(from_attributes=True, validate_by_name=True, validate_by_alias=True)

    from_: int = Field(alias="from")
    to: int
    added: list[SnapshotItem]
    removed: list[SnapshotItem]
    unchanged: list[SnapshotItem]
