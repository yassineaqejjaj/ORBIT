"""API payloads of the Microsoft Teams integration (owner configuration)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel, InputModel


class TeamsUserLink(InputModel):
    teams_id: str = Field(min_length=3, max_length=320, description="aadObjectId ou e-mail Teams")
    user_id: uuid.UUID


class TeamsUserLinkOut(ApiModel):
    teams_id: str
    user_id: uuid.UUID
    user_label: str = ""
    is_member: bool = True


class TeamsIntegrationIn(InputModel):
    secret: str | None = Field(
        default=None, min_length=16, max_length=500, description="Jeton de sécurité (base64) fourni par Teams"
    )
    enabled: bool = True
    app_url: str | None = Field(
        default=None, max_length=500, description="URL publique de l'application ORBIT"
    )
    user_mapping: list[TeamsUserLink] = Field(default_factory=list, max_length=500)


class TeamsIntegrationOut(ApiModel):
    configured: bool
    enabled: bool = False
    encryption_available: bool
    webhook_path: str
    app_url: str = ""
    user_mapping: list[TeamsUserLinkOut] = Field(default_factory=list)
    updated_at: datetime | None = None


__all__ = ["TeamsIntegrationIn", "TeamsIntegrationOut", "TeamsUserLink", "TeamsUserLinkOut"]
