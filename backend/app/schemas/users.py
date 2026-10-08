"""Users & authentication payloads."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel, ClassificationLevel, Email, InputModel


class User(ApiModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_admin: bool
    clearance: int
    avatar_color: str
    created_at: datetime


class UserRef(ApiModel):
    id: uuid.UUID
    full_name: str


class LoginIn(InputModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    #: « Rester connecté » — False issues a browser-session cookie (dropped when the browser closes).
    remember: bool = True


class UserCreateIn(InputModel):
    email: Email
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=256)
    clearance: ClassificationLevel = 1
    is_admin: bool = False


class UserUpdateIn(InputModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    clearance: ClassificationLevel | None = None
    is_admin: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)
