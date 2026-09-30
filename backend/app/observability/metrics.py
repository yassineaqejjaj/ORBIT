"""Prometheus metrics (ARCHITECTURE §11, PRODUCTION §3 « Exploitation ») and the ``/metrics`` ASGI app.

Metric objects are module-level singletons; prefer the ``observe_*`` / ``record_*`` helpers so label
sets stay consistent across teammates' code. Label values are always bounded (route templates, not
raw paths; dependency / operation names chosen in code).

``/metrics`` protection (PRODUCTION §1): when ``ORBIT_METRICS_TOKEN`` is set every scrape must send
``Authorization: Bearer <token>``; otherwise the public API answers 404 and metrics are only served
on the internal port ``ORBIT_METRICS_PORT`` (see :mod:`app.observability.internal_server`).
With several uvicorn processes set ``PROMETHEUS_MULTIPROC_DIR`` so the internal endpoint aggregates
every process.
"""

from __future__ import annotations

import hmac
import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from starlette.types import ASGIApp, Receive, Scope, Send

from app.observability.runtime_config import opt

# --- Context engine -----------------------------------------------------------------------------------
CONTEXT_REQUESTS_TOTAL = Counter(
    "orbit_context_requests_total",
    "Context requests served, by outcome and caller type.",
    ["status", "caller"],
)
CONTEXT_LATENCY_SECONDS = Histogram(
    "orbit_context_latency_seconds",
    "End-to-end latency of context assembly.",
    buckets=(0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0),
)
CONTEXT_TOKENS = Histogram(
    "orbit_context_tokens",
    "Tokens used by served context packages.",
    buckets=(250, 500, 1000, 2000, 4000, 8000, 16000, 32000),
)
EXCLUSIONS_TOTAL = Counter(
    "orbit_exclusions_total",
    "Candidates excluded from context packages, by reason code.",
    ["reason"],
)

# --- HTTP (RED) -------------------------------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "orbit_http_requests_total",
    "HTTP requests by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "orbit_http_request_duration_seconds",
    "HTTP request duration by method and route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
HTTP_IN_FLIGHT = Gauge("orbit_http_requests_in_flight", "HTTP requests currently being served.")

# --- Jobs & worker ----------------------------------------------------------------------------------------
INGESTION_JOBS_TOTAL = Counter(
    "orbit_ingestion_jobs_total",
    "Job outcomes: succeeded, failed (permanent), dead (dead letter), retried, cancelled, requeued.",
    ["status"],
)
JOB_DURATION_SECONDS = Histogram(
    "orbit_job_duration_seconds",
    "Job processing time by kind and outcome.",
    ["kind", "status"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 900.0),
)
WORKER_INFLIGHT = Gauge("orbit_worker_inflight_jobs", "Jobs currently processed by this worker.")
WORKER_LAST_LOOP_TIMESTAMP = Gauge(
    "orbit_worker_last_loop_timestamp_seconds", "Unix time of the last worker heartbeat loop iteration."
)
QUEUE_JOBS = Gauge("orbit_queue_jobs", "Jobs in the queue by status and kind.", ["status", "kind"])
QUEUE_OLDEST_AGE_SECONDS = Gauge(
    "orbit_queue_oldest_queued_age_seconds", "Age of the oldest runnable queued job, by kind.", ["kind"]
)
SCHEDULED_TASK_RUNS_TOTAL = Counter(
    "orbit_scheduled_task_runs_total", "Cluster-wide singleton task runs by task and outcome.", ["task", "status"]
)

# --- Dependencies & degraded mode -------------------------------------------------------------------------
DEPENDENCY_LATENCY_SECONDS = Histogram(
    "orbit_dependency_latency_seconds",
    "Latency of calls to dependencies (postgres, opensearch, valkey, embeddings, llm, object_store).",
    ["dependency", "operation"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
DEPENDENCY_ERRORS_TOTAL = Counter(
    "orbit_dependency_errors_total", "Failed calls to dependencies.", ["dependency", "operation"]
)
DEPENDENCY_UP = Gauge(
    "orbit_dependency_up", "Last health check result per dependency (1 ok, 0.5 degraded, 0 down).", ["dependency"]
)
DEGRADED_TOTAL = Counter(
    "orbit_degraded_operations_total",
    "Operations served in degraded mode (e.g. Postgres full-text fallback when OpenSearch is down).",
    ["component", "reason"],
)
INDEX_DRIFT_DOCUMENTS = Gauge(
    "orbit_index_drift_documents",
    "Postgres ↔ OpenSearch differences found by the last drift check (missing, orphan, status).",
    ["kind", "type"],
)


def observe_context_request(
    *,
    latency_seconds: float,
    tokens_used: int,
    exclusions: Mapping[str, int] | None = None,
    status: str = "succeeded",
    caller: str = "user",
) -> None:
    """Record one context request (call once per request, success or failure)."""
    CONTEXT_REQUESTS_TOTAL.labels(status=status, caller=caller).inc()
    if status == "succeeded":
        CONTEXT_LATENCY_SECONDS.observe(max(latency_seconds, 0.0))
        CONTEXT_TOKENS.observe(max(tokens_used, 0))
    for reason, count in (exclusions or {}).items():
        if count:
            EXCLUSIONS_TOTAL.labels(reason=str(reason)).inc(count)


def record_ingestion_job(status: str) -> None:
    """``status`` ∈ {succeeded, failed, dead, retried, cancelled, requeued}."""
    INGESTION_JOBS_TOTAL.labels(status=status).inc()


def observe_http_request(method: str, route: str, status: int, duration_seconds: float) -> None:
    HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=str(status)).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(max(duration_seconds, 0.0))


def record_degraded(component: str, reason: str) -> None:
    """Count one operation served in degraded mode (``component`` e.g. ``search``, ``context``)."""
    DEGRADED_TOTAL.labels(component=component, reason=reason).inc()


def record_dependency_error(dependency: str, operation: str) -> None:
    DEPENDENCY_ERRORS_TOTAL.labels(dependency=dependency, operation=operation).inc()


def set_dependency_status(dependency: str, status: str) -> None:
    """``status`` ∈ {ok, degraded, down, disabled…} → gauge 1 / 0.5 / 0."""
    value = {"ok": 1.0, "disabled": 1.0, "not_implemented": 1.0, "degraded": 0.5}.get(status, 0.0)
    DEPENDENCY_UP.labels(dependency=dependency).set(value)


@contextmanager
def track_dependency(dependency: str, operation: str) -> Iterator[None]:
    """Time a dependency call and count its failures (the exception is re-raised)."""
    started = time.perf_counter()
    try:
        yield
    except BaseException as exc:
        if not isinstance(exc, GeneratorExit):
            DEPENDENCY_ERRORS_TOTAL.labels(dependency=dependency, operation=operation).inc()
        raise
    finally:
        DEPENDENCY_LATENCY_SECONDS.labels(dependency=dependency, operation=operation).observe(
            time.perf_counter() - started
        )


# --- Collectors -------------------------------------------------------------------------------------------


class _PoolCollector(Collector):
    """SQLAlchemy pool usage (checked-out / idle / overflow connections)."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def collect(self) -> Iterator[GaugeMetricFamily]:
        pool = getattr(self._engine, "pool", None)
        family = GaugeMetricFamily("orbit_db_pool_connections", "Database pool connections by state.", labels=["state"])
        for state, getter in (("checked_out", "checkedout"), ("idle", "checkedin"), ("overflow", "overflow")):
            method = getattr(pool, getter, None)
            if callable(method):
                try:
                    family.add_metric([state], float(method()))
                except Exception:  # pragma: no cover - pool implementation without counters
                    continue
        yield family


_pool_collector: _PoolCollector | None = None


def register_db_pool_collector(engine: Any) -> None:
    """Expose pool gauges for ``engine`` (idempotent; the latest engine wins)."""
    global _pool_collector
    if _pool_collector is not None:
        _pool_collector._engine = engine
        return
    _pool_collector = _PoolCollector(engine)
    REGISTRY.register(_pool_collector)


# --- Exposition ---------------------------------------------------------------------------------------------


def metrics_payload() -> tuple[bytes, str]:
    """Current exposition (aggregated over processes when ``PROMETHEUS_MULTIPROC_DIR`` is set)."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def metrics_token() -> str:
    return str(opt("metrics_token", "") or "")


def authorized_scrape(authorization: str | None, *, internal: bool) -> bool:
    """Scrape policy: token (if configured) always required; without token only the internal port serves."""
    token = metrics_token()
    if token:
        expected = f"Bearer {token}"
        return bool(authorization) and hmac.compare_digest(str(authorization).encode(), expected.encode())
    return internal


class MetricsApp:
    """ASGI ``/metrics`` endpoint enforcing :func:`authorized_scrape`."""

    def __init__(self, *, internal: bool = False) -> None:
        self.internal = internal

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        authorization = None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                authorization = value.decode("latin-1")
                break
        if not authorized_scrape(authorization, internal=self.internal):
            status = 401 if metrics_token() else 404
            body = b'{"detail":"Non autoris\\u00e9","code":"unauthorized"}' if status == 401 else b'{"detail":"Introuvable","code":"not_found"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        payload, content_type = metrics_payload()
        await send(
            {"type": "http.response.start", "status": 200, "headers": [(b"content-type", content_type.encode())]}
        )
        await send({"type": "http.response.body", "body": payload})


def metrics_asgi_app(*, internal: bool = False) -> ASGIApp:
    """ASGI app exposing the registry (mounted on ``/metrics``; token/internal-port policy enforced)."""
    return MetricsApp(internal=internal)
