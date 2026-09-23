"""Per-request context (request id) shared by logging, error handlers and audit."""

from __future__ import annotations

import secrets
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("orbit_request_id", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> object:
    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]


def new_request_id() -> str:
    return secrets.token_hex(8)
