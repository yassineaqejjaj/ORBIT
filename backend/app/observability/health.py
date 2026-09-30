"""Dependency health checks shared by ``/ready``, ``GET /ops/status`` and ``python -m app.admin status``.

Each check returns a :class:`DependencyStatus`; checks never raise. ``required`` dependencies
(Postgres, OpenSearch) decide readiness; optional ones (Valkey, models) only degrade the service.
The result also feeds the ``orbit_dependency_up`` gauge.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import text

from app.observability.metrics import record_dependency_error, set_dependency_status

CHECK_TIMEOUT_SECONDS = 3.0


@dataclass(slots=True)
class DependencyStatus:
    name: str
    #: ``ok`` | ``error`` | ``not_implemented``
    status: str
    required: bool
    latency_ms: float | None = None
    detail: str | None = None
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "not_implemented", "disabled"}

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def timed_check(
    name: str,
    check: Callable[[], Awaitable[dict[str, Any] | None]],
    *,
    required: bool,
    limit_seconds: float = CHECK_TIMEOUT_SECONDS,
) -> DependencyStatus:
    started = time.perf_counter()
    try:
        info = await asyncio.wait_for(check(), timeout=limit_seconds)
        result = DependencyStatus(
            name, "ok", required, latency_ms=round((time.perf_counter() - started) * 1000, 1), info=info or {}
        )
    except NotImplementedError:
        result = DependencyStatus(name, "not_implemented", required)
    except TimeoutError:
        result = DependencyStatus(name, "error", required, detail="Délai dépassé")
    except Exception as exc:
        result = DependencyStatus(name, "error", required, detail=str(exc)[:300] or type(exc).__name__)
    if not result.ok:
        record_dependency_error(name, "health_check")
    set_dependency_status(name, "ok" if result.ok else ("degraded" if not required else "down"))
    return result


async def _postgres() -> dict[str, Any]:
    from app.db import get_engine

    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
        revision = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    return {"migration": revision}


async def _opensearch() -> dict[str, Any]:
    from app.search import opensearch

    return await opensearch.ping()


async def _valkey() -> dict[str, Any]:
    from app.memory.short_term import get_valkey

    await get_valkey().ping()
    return {}


async def check_postgres() -> DependencyStatus:
    return await timed_check("postgres", _postgres, required=True)


async def check_opensearch() -> DependencyStatus:
    return await timed_check("opensearch", _opensearch, required=True)


async def check_valkey() -> DependencyStatus:
    return await timed_check("valkey", _valkey, required=False)


async def check_core_dependencies() -> list[DependencyStatus]:
    """Postgres, OpenSearch and Valkey, checked concurrently (models are checked by ``/ready`` only)."""
    return list(await asyncio.gather(check_postgres(), check_opensearch(), check_valkey()))
