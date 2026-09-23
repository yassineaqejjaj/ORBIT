"""Column types and helpers shared by the models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Dialect, Text
from sqlalchemy.types import TypeDecorator

from app.enums import check_in


class StrEnumType[E: StrEnum](TypeDecorator[E]):
    """Stores a ``StrEnum`` as ``text`` (enforced by a ``CHECK`` constraint) and loads it back as the enum."""

    impl = Text
    cache_ok = True

    def __init__(self, enum_cls: type[E], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.enum_cls = enum_cls

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return self.enum_cls(value).value

    def process_result_value(self, value: Any, dialect: Dialect) -> E | None:
        if value is None:
            return None
        return self.enum_cls(value)

    @property
    def python_type(self) -> type[E]:
        return self.enum_cls


def enum_check(column: str, enum_cls: type[StrEnum]) -> CheckConstraint:
    """Named ``CHECK`` constraint (``ck_<table>_<column>``) restricting a text column to enum values."""
    return CheckConstraint(check_in(column, enum_cls), name=column)


def range_check(
    column: str, low: int | float, high: int | float, *, nullable: bool = False
) -> CheckConstraint:
    expr = f"{column} BETWEEN {low} AND {high}"
    if nullable:
        expr = f"{column} IS NULL OR ({expr})"
    return CheckConstraint(expr, name=f"{column}_range")


CLASSIFICATION_CHECK_RANGE = (0, 3)
