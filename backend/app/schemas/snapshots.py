"""Versioned, immutable context snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from app.enums import CandidateType, Intent, MemoryKind, SourceKind
from app.schemas.common import ApiModel


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
    content: str
    items: list[SnapshotItem]
    request_id: uuid.UUID | None


class SnapshotDiff(ApiModel):
    model_config = ConfigDict(from_attributes=True, validate_by_name=True, validate_by_alias=True)

    from_: int = Field(alias="from")
    to: int
    added: list[SnapshotItem]
    removed: list[SnapshotItem]
    unchanged: list[SnapshotItem]
