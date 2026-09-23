"""System endpoints (health, readiness, meta)."""

from __future__ import annotations

from typing import Any, Literal

from app.schemas.common import ApiModel


class Health(ApiModel):
    status: Literal["ok"] = "ok"


class DependencyCheck(ApiModel):
    status: Literal["ok", "error", "not_implemented", "disabled"]
    latency_ms: float | None = None
    detail: str | None = None
    info: dict[str, Any] | None = None


class Ready(ApiModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, DependencyCheck]


class Meta(ApiModel):
    version: str
    embedding_model: str
    reranker: str
    llm: str | None
    reason_codes: dict[str, str]
