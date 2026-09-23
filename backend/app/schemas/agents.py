"""AI agents and their API keys."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.enums import AgentKind
from app.schemas.common import ApiModel, ClassificationLevel, InputModel


class Agent(ApiModel):
    id: uuid.UUID
    name: str
    kind: AgentKind
    description: str
    clearance: int
    api_key_prefix: str
    active: bool
    created_at: datetime
    last_used_at: datetime | None


class AgentCreated(ApiModel):
    agent: Agent
    api_key: str = Field(description="Clé complète, affichée une seule fois")


class AgentRef(ApiModel):
    id: uuid.UUID
    name: str
    kind: AgentKind


class AgentCreateIn(InputModel):
    name: str = Field(min_length=1, max_length=120)
    kind: AgentKind = AgentKind.custom
    description: str = Field(default="", max_length=2000)
    clearance: ClassificationLevel = 1
