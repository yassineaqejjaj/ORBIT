"""Audit events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.enums import ActorType
from app.schemas.common import ApiModel


class AuditEvent(ApiModel):
    id: uuid.UUID
    actor_type: ActorType
    actor_id: uuid.UUID | None
    actor_label: str
    action: str
    target_type: str
    target_id: str | None
    summary: str
    details: dict[str, Any]
    created_at: datetime
