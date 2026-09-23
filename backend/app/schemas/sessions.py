"""Short-term memory sessions (agent turns buffered in Valkey)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.enums import TurnRole
from app.schemas.common import ApiModel, InputModel
from app.schemas.memory import MemoryItem


class TurnIn(InputModel):
    role: TurnRole
    content: str = Field(min_length=1, max_length=50_000)
    agent_id: uuid.UUID | None = None


class TurnAppendOut(ApiModel):
    session_id: str
    turns: int
    expires_at: datetime


class SessionTurn(ApiModel):
    role: TurnRole
    content: str
    at: datetime


class SessionDetail(ApiModel):
    session_id: str
    turns: list[SessionTurn]
    expires_at: datetime | None
    memory_items: list[MemoryItem]


class SessionCloseOut(ApiModel):
    summary: MemoryItem | None


class SessionSummary(ApiModel):
    session_id: str
    turns: int
    updated_at: datetime
    expires_at: datetime | None
