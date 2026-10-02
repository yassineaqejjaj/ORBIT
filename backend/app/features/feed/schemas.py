"""API payloads of the change feed, subscriptions and webhooks (docs/FEATURES.md F2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.features.feed.types import normalize_types
from app.schemas.common import ApiModel, InputModel


class ChangeEventOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    type: str
    type_label: str = ""
    title: str
    summary: str
    target_type: str
    target_id: str | None
    classification: int
    actor_label: str
    created_at: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class SnapshotRef(ApiModel):
    id: uuid.UUID
    name: str
    version: int
    created_at: datetime


class OutdatedItem(ApiModel):
    item_type: Literal["memory", "document"]
    id: uuid.UUID
    title: str
    reason: Literal["superseded", "forgotten", "obsolete", "edited", "new_version", "stale"]
    detail: str
    replaced_by_id: uuid.UUID | None = None
    replaced_by_title: str | None = None


class SinceSnapshot(ApiModel):
    snapshot: SnapshotRef
    total: int
    changes: list[ChangeEventOut]
    outdated: list[OutdatedItem]
    hidden_outdated: int = 0
    is_up_to_date: bool


class DigestGroup(ApiModel):
    type: str
    label: str
    count: int
    items: list[ChangeEventOut]


class Digest(ApiModel):
    period: Literal["day", "week"]
    since: datetime
    until: datetime
    total: int
    groups: list[DigestGroup]
    text: str
    email_enabled: bool


DigestFrequency = Literal["off", "daily", "weekly"]


class SubscriptionOut(ApiModel):
    digest: DigestFrequency
    types: list[str]
    last_digest_at: datetime | None = None
    email_enabled: bool = False


class SubscriptionIn(InputModel):
    digest: DigestFrequency = "off"
    types: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("types")
    @classmethod
    def _types(cls, value: list[str]) -> list[str]:
        return normalize_types(value)


class WebhookOut(ApiModel):
    id: uuid.UUID
    url: str
    description: str
    types: list[str]
    enabled: bool
    secret_hint: str
    consecutive_failures: int
    disabled_reason: str | None
    last_delivery_at: datetime | None
    last_status: str | None
    created_at: datetime
    updated_at: datetime


class WebhookCreated(WebhookOut):
    #: Shown once, never returned again.
    secret: str


class WebhookIn(InputModel):
    url: str = Field(min_length=8, max_length=2000)
    types: list[str] = Field(default_factory=list, max_length=50)
    description: str = Field(default="", max_length=500)

    @field_validator("types")
    @classmethod
    def _types(cls, value: list[str]) -> list[str]:
        return normalize_types(value)


class WebhookPatch(InputModel):
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    types: list[str] | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None

    @field_validator("types")
    @classmethod
    def _types(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_types(value)


class WebhookDeliveryOut(ApiModel):
    id: uuid.UUID
    webhook_id: uuid.UUID
    change_event_id: uuid.UUID | None
    event_type: str
    status: str
    attempts: int
    response_status: int | None
    error: str | None
    duration_ms: float | None
    payload: dict[str, Any]
    created_at: datetime
    delivered_at: datetime | None
