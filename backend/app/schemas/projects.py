"""Projects, settings, members and the project overview."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.enums import AlertLevel, MemoryScope, MemoryStatus, Role, SourceKind
from app.schemas.audit import AuditEvent
from app.schemas.common import ApiModel, Email, InputModel, Slug
from app.schemas.memory import MemoryItem
from app.schemas.users import User


class ProjectSettings(ApiModel):
    freshness_days: dict[SourceKind, int]
    default_token_budget: int = Field(ge=500, le=32000)
    min_relevance: float = Field(ge=0, le=1)
    short_term_ttl_hours: int = Field(ge=1, le=24 * 90)


class ProjectSettingsPatch(InputModel):
    """Partial settings; ``freshness_days`` is merged key by key."""

    freshness_days: dict[SourceKind, int] | None = None
    default_token_budget: int | None = Field(default=None, ge=500, le=32000)
    min_relevance: float | None = Field(default=None, ge=0, le=1)
    short_term_ttl_hours: int | None = Field(default=None, ge=1, le=24 * 90)


class Project(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    settings: ProjectSettings
    role: Role
    created_at: datetime
    updated_at: datetime


class ProjectStats(ApiModel):
    sources: int = 0
    documents: int = 0
    memory_items: int = 0
    context_requests_7d: int = 0


class ProjectSummary(Project):
    stats: ProjectStats


class ProjectCreateIn(InputModel):
    name: str = Field(min_length=1, max_length=120)
    slug: Slug | None = None
    description: str = Field(default="", max_length=2000)


class ProjectUpdateIn(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    settings: ProjectSettingsPatch | None = None


class Member(ApiModel):
    user: User
    role: Role
    created_at: datetime


class MemberAddIn(InputModel):
    email: Email
    role: Role = Role.viewer


class MemberUpdateIn(InputModel):
    role: Role


# --- Overview -------------------------------------------------------------------------------------


class OverviewStats(ApiModel):
    sources: int = 0
    documents: int = 0
    documents_indexed: int = 0
    chunks: int = 0
    memory_items: int = 0
    validated_decisions: int = 0
    context_requests_7d: int = 0
    snapshots: int = 0
    pii_documents: int = 0
    restricted_documents: int = 0


class OverviewIngestion(ApiModel):
    queued: int = 0
    running: int = 0
    failed: int = 0
    succeeded_24h: int = 0


class OverviewContext(ApiModel):
    requests_7d: int = 0
    p95_latency_ms: float = 0
    avg_tokens: float = 0
    avg_included: float = 0
    exclusion_rate: float = 0


class Alert(ApiModel):
    level: AlertLevel
    message: str


class Overview(ApiModel):
    project: Project
    stats: OverviewStats
    ingestion: OverviewIngestion
    memory_by_status: dict[MemoryStatus, int]
    memory_by_scope: dict[MemoryScope, int]
    context: OverviewContext
    sources_by_kind: dict[SourceKind, int]
    latest_decisions: list[MemoryItem]
    recent_activity: list[AuditEvent]
    alerts: list[Alert]
