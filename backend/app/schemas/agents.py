"""AI agents and their API keys."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

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
    #: Explicit project role (``viewer`` | ``editor``), optional expiry and last rotation (NOV-112).
    role: Literal["viewer", "editor"] = "editor"
    expires_at: datetime | None = None
    rotated_at: datetime | None = None


class AgentCreated(ApiModel):
    agent: Agent
    api_key: str = Field(description="Clé complète, affichée une seule fois")


class AgentSelfProject(ApiModel):
    id: uuid.UUID
    slug: str
    name: str


class AgentSelfKey(ApiModel):
    prefix: str
    #: Always ``active``: a revoked or unknown key is refused (401) before reaching the endpoint.
    status: Literal["active"] = "active"
    created_at: datetime
    last_used_at: datetime | None


class AgentSelf(ApiModel):
    """What an agent key says about itself (``GET /agents/self``), for link-health screens."""

    id: uuid.UUID
    name: str
    kind: AgentKind
    description: str
    clearance: int
    project: AgentSelfProject
    key: AgentSelfKey


class AgentRef(ApiModel):
    id: uuid.UUID
    name: str
    kind: AgentKind


class AgentCreateIn(InputModel):
    name: str = Field(min_length=1, max_length=120)
    kind: AgentKind = AgentKind.custom
    description: str = Field(default="", max_length=2000)
    clearance: ClassificationLevel = 1
    #: ``viewer`` keys read, ``editor`` keys (default) also propose; never ``owner`` (ADR 001 §7).
    role: Literal["viewer", "editor"] = "editor"
    #: Optional lifetime of the key in days (``None`` = no expiry).
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class AgentRotateIn(InputModel):
    """Optional body of a rotation: a new lifetime in days from now; absent keeps the current expiry."""

    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
