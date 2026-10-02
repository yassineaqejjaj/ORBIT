"""API payloads of the memory triage inbox and conflict arbitration (docs/FEATURES.md F1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel, InputModel
from app.schemas.memory import MemoryItem, Provenance


class SimilarItem(ApiModel):
    id: uuid.UUID
    title: str
    score: float


class InboxItem(MemoryItem):
    impact: int = 0
    would_be_included: int = 0
    similar: SimilarItem | None = None


class InboxCount(ApiModel):
    proposals: int
    conflicts: int
    total: int


class BulkIn(InputModel):
    action: Literal["validate", "reject", "merge"]
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    into_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _merge_target(self) -> BulkIn:
        if self.action == "merge" and self.into_id is None:
            raise ValueError("« into_id » est obligatoire pour une fusion")
        return self


class BulkFailure(ApiModel):
    id: uuid.UUID
    detail: str


class BulkOut(ApiModel):
    processed: int
    failed: list[BulkFailure]


class ConflictSide(MemoryItem):
    sources: list[Provenance] = Field(default_factory=list)


class ConflictResolutionOut(ApiModel):
    status: Literal["resolved", "dismissed"]
    winner_id: uuid.UUID | None
    reason: str | None
    resolved_by: str
    resolved_at: datetime


class Conflict(ApiModel):
    id: uuid.UUID
    a: ConflictSide
    b: ConflictSide
    detected_at: datetime
    similarity: float
    detail: str | None
    suggested_winner_id: uuid.UUID
    rationale: str
    status: Literal["open", "resolved", "dismissed"]
    resolution: ConflictResolutionOut | None = None


class ResolveIn(InputModel):
    winner_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=2000)


class DismissIn(InputModel):
    reason: str | None = Field(default=None, max_length=2000)
