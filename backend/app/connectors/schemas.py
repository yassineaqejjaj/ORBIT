"""API models of the connectors (docs/FEATURES.md F5).

Secrets are write-only: only a masked hint is returned.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel, InputModel

ConnectorType = Literal["sharepoint", "confluence", "jira", "mcp"]
SCHEDULE_MAX_MINUTES = 7 * 24 * 60


class ConnectorIn(InputModel):
    type: ConnectorType
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str = Field(min_length=1, max_length=4000)
    #: ``0`` = manual syncs only; default ``ORBIT_CONNECTOR_DEFAULT_SCHEDULE_MINUTES``.
    schedule_minutes: int | None = Field(default=None, ge=0, le=SCHEDULE_MAX_MINUTES)
    default_classification: int = Field(default=1, ge=0, le=3)
    restrict_to_editors: bool = False
    #: Queue the first synchronisation right away (wizard step 4).
    start_sync: bool = False


class ConnectorPatch(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    config: dict[str, Any] | None = None
    #: New secret (rotation); omitted = unchanged.
    secret: str | None = Field(default=None, min_length=1, max_length=4000)
    schedule_minutes: int | None = Field(default=None, ge=0, le=SCHEDULE_MAX_MINUTES)
    default_classification: int | None = Field(default=None, ge=0, le=3)
    restrict_to_editors: bool | None = None
    paused: bool | None = None


class ConnectorTestIn(InputModel):
    """Credentials check before creation (wizard step 2): nothing is stored nor ingested."""

    type: ConnectorType
    config: dict[str, Any] = Field(default_factory=dict)
    secret: str = Field(min_length=1, max_length=4000)


class ConnectorRetestIn(InputModel):
    """Check of a saved connector, optionally with edited (unsaved) settings or a new secret."""

    config: dict[str, Any] | None = None
    secret: str | None = Field(default=None, min_length=1, max_length=4000)


class ScopeOptionOut(ApiModel):
    id: str
    label: str
    kind: str
    parent_id: str | None = None
    description: str = ""


class ConnectorTestOut(ApiModel):
    ok: bool
    message: str
    account: str | None = None
    scope_options: list[ScopeOptionOut] = Field(default_factory=list)
    #: Tools discovered on the MCP server (MCP connectors).
    tools: list[str] = Field(default_factory=list)
    duration_ms: float


class ConnectorRunOut(ApiModel):
    id: uuid.UUID
    connector_id: uuid.UUID
    trigger: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: float | None
    fetched: int
    created: int
    updated: int
    unchanged: int
    skipped: int
    forgotten: int
    errors: int
    progress: dict[str, Any]
    error_samples: list[dict[str, Any]]
    error: str | None
    created_at: datetime


class ConnectorOut(ApiModel):
    id: uuid.UUID
    type: ConnectorType
    type_label: str
    #: MCP preset id (``type == "mcp"``).
    preset: str | None = None
    via_mcp: bool = False
    name: str
    config: dict[str, Any]
    has_secret: bool
    secret_hint: str
    schedule_minutes: int
    status: str
    paused: bool
    default_classification: int
    restrict_to_editors: bool
    acl_principals: list[str]
    last_sync_at: datetime | None
    last_error: str | None
    source_id: uuid.UUID | None
    document_count: int = 0
    last_run: ConnectorRunOut | None = None
    suggested_task: str
    created_at: datetime
    updated_at: datetime


class PresetFieldOut(ApiModel):
    key: str
    label: str
    group: Literal["secret", "connection", "scope"]
    kind: str
    required: bool = False
    help: str = ""
    placeholder: str = ""
    default: Any = None
    options: list[dict[str, str]] = Field(default_factory=list)
    visible_if: str | None = None


class ConnectorTypeOut(ApiModel):
    type: ConnectorType
    label: str
    source_kind: str
    #: MCP presets (``type == "mcp"``): one entry per preset.
    preset: str | None = None
    via_mcp: bool = False
    description: str = ""
    vendor: str = ""
    icon: str = ""
    transport: str | None = None
    version: str = ""
    docs_url: str = ""
    credentials_help: str = ""
    required_tools: list[str] = Field(default_factory=list)
    fields: list[PresetFieldOut] = Field(default_factory=list)
    admin_only: bool = False
