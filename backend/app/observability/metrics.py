"""Prometheus metrics (ARCHITECTURE §11) and the ``/metrics`` ASGI app.

Metric objects are module-level singletons; prefer the ``observe_*`` / ``record_*`` helpers so label
sets stay consistent across teammates' code.
"""

from __future__ import annotations

from collections.abc import Mapping

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from starlette.types import ASGIApp

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
INGESTION_JOBS_TOTAL = Counter(
    "orbit_ingestion_jobs_total",
    "Ingestion jobs by final status (succeeded, failed) or retry.",
    ["status"],
)
EXCLUSIONS_TOTAL = Counter(
    "orbit_exclusions_total",
    "Candidates excluded from context packages, by reason code.",
    ["reason"],
)
WORKER_INFLIGHT = Gauge("orbit_worker_inflight_jobs", "Jobs currently processed by this worker.")

CONTEXT_CACHE_PREFIX_TOTAL = Counter(
    "orbit_context_cache_prefix_total",
    "Context packages by stable-prefix reuse (hit: same prefix served within the cache window).",
    ["result"],
)
CONTEXT_CACHE_PREFIX_TOKENS_TOTAL = Counter(
    "orbit_context_cache_prefix_tokens_total",
    "Tokens of stable prefixes served, by reuse result (hit = cacheable tokens).",
    ["result"],
)
CONTEXT_EVENTS_TOTAL = Counter(
    "orbit_context_events_total",
    "`context.served` change events, by outcome (emitted, coalesced, skipped).",
    ["outcome"],
)
LIVE_EVENTS_PUBLISHED_TOTAL = Counter(
    "orbit_live_events_published_total", "Live events published on the bus, by kind.", ["kind"]
)
LIVE_EVENTS_DELIVERED_TOTAL = Counter(
    "orbit_live_events_delivered_total", "Live events written to SSE clients, by kind.", ["kind"]
)
LIVE_CONNECTIONS = Gauge("orbit_live_stream_connections", "Open SSE connections on this process.")


def observe_cache_prefix(*, reused: bool, tokens: int) -> None:
    """§C1: one served package with a stable prefix."""
    result = "hit" if reused else "miss"
    CONTEXT_CACHE_PREFIX_TOTAL.labels(result=result).inc()
    CONTEXT_CACHE_PREFIX_TOKENS_TOTAL.labels(result=result).inc(max(tokens, 0))


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
    """``status`` ∈ {succeeded, failed, retried}."""
    INGESTION_JOBS_TOTAL.labels(status=status).inc()


def metrics_asgi_app() -> ASGIApp:
    """ASGI app exposing the default registry (mounted on ``/metrics``)."""
    return make_asgi_app()
