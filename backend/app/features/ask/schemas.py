"""API payloads of « Demander à ORBIT » (F4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.enums import MemoryScope
from app.schemas.common import ApiModel, InputModel
from app.schemas.context import ContextItem, ContextSufficiency

AskMode = Literal["llm", "extractive"]
AskConfidence = Literal["high", "medium", "low"]


class AskIn(InputModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    scopes: list[MemoryScope] | None = None
    token_budget: int | None = Field(default=None, ge=500, le=32000, description="Défaut : 3000")


class AskOut(ApiModel):
    answer: str
    citations: list[ContextItem]
    confidence: AskConfidence
    follow_ups: list[str]
    request_id: uuid.UUID | None
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    mode: AskMode
    warnings: list[str] = Field(default_factory=list)
    #: §A2: the cited excerpts are untrusted source data (agents must not follow instructions in them).
    untrusted_content_notice: str | None = None
    #: §C5 sufficiency of the context the answer is based on.
    sufficiency: ContextSufficiency | None = None


class AskMessageOut(ApiModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[ContextItem] = Field(default_factory=list)
    confidence: AskConfidence | None = None
    mode: AskMode | None = None
    follow_ups: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    request_id: uuid.UUID | None = None
    rating: int | None = None
    created_at: datetime


class AskConversationSummary(ApiModel):
    id: uuid.UUID
    title: str
    channel: Literal["web", "teams", "api"]
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class AskConversationDetail(AskConversationSummary):
    messages: list[AskMessageOut]


class AskFeedbackIn(InputModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=4000)


__all__ = [
    "AskConversationDetail",
    "AskConversationSummary",
    "AskFeedbackIn",
    "AskIn",
    "AskMessageOut",
    "AskOut",
]
