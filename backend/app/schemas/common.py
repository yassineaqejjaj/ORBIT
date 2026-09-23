"""Shared Pydantic building blocks: base model, pagination, errors, validated field types."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from email_validator import EmailNotValidError, validate_email
from fastapi import Query
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.governance.acl import validate_acl_principals


class ApiModel(BaseModel):
    """Base for API payloads: reads ORM objects, accepts field names or aliases."""

    model_config = ConfigDict(from_attributes=True, validate_by_name=True, validate_by_alias=True)


class InputModel(BaseModel):
    """Base for request bodies: unknown fields are rejected, strings are stripped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorOut(BaseModel):
    detail: str
    code: str


class IdOut(ApiModel):
    id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def page_params(
    page: Annotated[int, Query(ge=1, description="Page (1-based)")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Taille de page (max 100)")] = 25,
) -> PageParams:
    """FastAPI dependency: ``params: PageParams = Depends(page_params)``."""
    return PageParams(page=page, page_size=page_size)


def make_page[T](items: list[T], total: int, params: PageParams) -> Page[T]:
    return Page[T](items=items, total=total, page=params.page, page_size=params.page_size)


# --- Validated field types ------------------------------------------------------------------------

_BASIC_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    """Validate an e-mail address and return its lower-cased form.

    Internal/on-premise domains (``.local``, ``.internal``…) are accepted: email-validator rejects
    them as special-use names, which is wrong for an enterprise deployment.
    """
    candidate = value.strip()
    try:
        return validate_email(candidate, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        if "special-use" in str(exc) and _BASIC_EMAIL.match(candidate):
            return candidate.lower()
        raise ValueError("Adresse e-mail invalide") from exc


def _normalize_tags(values: list[str]) -> list[str]:
    result: list[str] = []
    for raw in values:
        tag = str(raw).strip()
        if tag and tag not in result:
            result.append(tag[:64])
    if len(result) > 50:
        raise ValueError("50 étiquettes maximum")
    return result


def _acl(values: list[str]) -> list[str]:
    return validate_acl_principals(values)


Email = Annotated[str, AfterValidator(normalize_email)]
ClassificationLevel = Annotated[int, Field(ge=0, le=3, description="0=C0 Public … 3=C3 Secret")]
AclPrincipals = Annotated[list[str], AfterValidator(_acl)]
Tags = Annotated[list[str], AfterValidator(_normalize_tags)]
Slug = Annotated[str, Field(min_length=2, max_length=48, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
JsonObject = dict[str, Any]
