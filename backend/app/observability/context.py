"""Per-request / per-job context shared by logging, error handlers, audit and tracing.

``request_id`` is set by :class:`app.observability.middleware.RequestContextMiddleware`; ``job_id`` and
``project`` are bound by the worker (:func:`bind_log_context`) so every log line of a job carries them.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("orbit_request_id", default=None)
_job_id: ContextVar[str | None] = ContextVar("orbit_job_id", default=None)
_project: ContextVar[str | None] = ContextVar("orbit_project", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str | None) -> object:
    return _request_id.set(value)


def reset_request_id(token: object) -> None:
    _request_id.reset(token)  # type: ignore[arg-type]


def new_request_id() -> str:
    return secrets.token_hex(8)


def get_job_id() -> str | None:
    return _job_id.get()


def get_project() -> str | None:
    return _project.get()


def set_project(value: str | None) -> object:
    """Bind the project (id or slug) of the current request/job for log correlation."""
    return _project.set(value)


@contextmanager
def bind_log_context(
    *, job_id: object | None = None, project: object | None = None, request_id: str | None = None
) -> Iterator[None]:
    """Bind correlation fields for the duration of the block (values are stringified)."""
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = []
    for var, value in ((_job_id, job_id), (_project, project), (_request_id, request_id)):
        if value is not None:
            tokens.append((var, var.set(str(value))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
