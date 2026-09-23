"""OpenTelemetry tracing.

A ``TracerProvider`` is always installed so every context request gets a real ``trace_id``. When
``ORBIT_OTLP_ENDPOINT`` is set (Langfuse, Jaeger, Tempo, an OTel collector…), spans are exported with
OTLP/HTTP. FastAPI is instrumented (health/ready/metrics excluded).

Usage in business code::

    from app.observability.tracing import get_tracer, current_trace_id
    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("context.retrieve") as span:
        span.set_attribute("orbit.candidates", 42)
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("orbit.tracing")

_provider: TracerProvider | None = None


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in raw.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            if key.strip():
                headers[key.strip()] = value.strip()
    return headers


def _traces_endpoint(endpoint: str) -> str:
    return endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"


def setup_tracing(service_name: str | None = None) -> TracerProvider:
    """Install the global tracer provider (idempotent)."""
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create(
        {
            "service.name": service_name or settings.service_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.env,
        }
    )
    provider = TracerProvider(resource=resource)
    if settings.otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(
                endpoint=_traces_endpoint(settings.otlp_endpoint),
                headers=_parse_headers(settings.otlp_headers) or None,
                timeout=10,
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTLP trace export enabled -> %s", _traces_endpoint(settings.otlp_endpoint))
        except Exception:  # pragma: no cover - exporter misconfiguration must not break startup
            logger.exception("Unable to configure the OTLP exporter; traces stay local")
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def instrument_fastapi(app: FastAPI) -> None:
    """Instrument a FastAPI app (server spans for every API route)."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=setup_tracing(),
            excluded_urls="health,ready,metrics",
        )
    except Exception:  # pragma: no cover
        logger.exception("FastAPI instrumentation failed")


def get_tracer(name: str = "orbit") -> trace.Tracer:
    setup_tracing()
    return trace.get_tracer(name)


def current_trace_id() -> str:
    """Hex trace id of the active span, or a fresh random id when no span is recording."""
    span_context = trace.get_current_span().get_span_context()
    if span_context and span_context.is_valid:
        return format(span_context.trace_id, "032x")
    return secrets.token_hex(16)


def shutdown_tracing() -> None:
    global _provider
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:  # pragma: no cover
            logger.warning("Tracer provider shutdown failed", exc_info=True)
    _provider = None
