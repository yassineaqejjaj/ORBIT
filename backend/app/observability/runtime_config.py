"""Read ops tunables that may not (yet) be declared in :class:`app.config.Settings`.

``app/config.py`` is owned by another workstream; ops code reads its optional knobs through
:func:`opt` so that a declared setting always wins, an undeclared one can still be set with its
``ORBIT_<NAME>`` environment variable, and the documented default applies otherwise.
"""

from __future__ import annotations

import os
from typing import Any, TypeVar, cast

from app.config import settings

T = TypeVar("T")

_TRUE = {"1", "true", "yes", "on"}


def _coerce(raw: str, default: Any) -> Any:
    if isinstance(default, bool):
        return raw.strip().lower() in _TRUE
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


def opt(name: str, default: T) -> T:
    """Value of setting ``name`` (declared field → env ``ORBIT_<NAME>`` → ``default``)."""
    if name in type(settings).model_fields:
        return cast(T, getattr(settings, name))
    raw = os.environ.get(f"ORBIT_{name.upper()}")
    if raw is None or raw == "":
        return default
    try:
        return cast(T, _coerce(raw, default))
    except ValueError:
        return default
