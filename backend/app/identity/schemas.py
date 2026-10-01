"""Payloads of the identity endpoints (docs/PRODUCTION.md §3 « Identité & compte »)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel, InputModel
from app.schemas.users import User as BaseUserOut
from app.schemas.users import UserCreateIn, UserUpdateIn


class UserOut(BaseUserOut):
    """``User`` enriched with the account lifecycle fields."""

    is_active: bool = True
    must_change_password: bool = False
    mfa_enabled: bool = False
    auth_provider: Literal["local", "oidc"] = "local"
    last_login_at: datetime | None = None


class AdminUserCreateIn(UserCreateIn):
    #: An administrator knows the initial password: it must be changed at the first login by default.
    must_change_password: bool = True


class AdminUserUpdateIn(UserUpdateIn):
    #: Defaults to ``true`` when an administrator sets someone else's password.
    must_change_password: bool | None = None


class OidcConfig(ApiModel):
    enabled: bool
    label: str


class AuthConfig(ApiModel):
    local_login: bool
    oidc: OidcConfig
    mfa_policy: Literal["none", "privileged", "all"]
    password_min_length: int


class CsrfOut(ApiModel):
    csrf_token: str


class MfaChallenge(ApiModel):
    mfa_required: Literal[True] = True
    mfa_token: str


class PasswordChangeChallenge(ApiModel):
    password_change_required: Literal[True] = True
    change_token: str


class PasswordChangeRequiredIn(InputModel):
    change_token: str = Field(min_length=1, max_length=4096)
    new_password: str = Field(min_length=1, max_length=256)


class AccountPasswordIn(InputModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class AccountSession(ApiModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    auth_method: str
    current: bool
