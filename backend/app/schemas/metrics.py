"""Observability aggregates for the UI (``GET /projects/{slug}/metrics``)."""

from __future__ import annotations

import datetime as dt
import uuid

from app.enums import AgentKind, DocumentStatus, JobStatus, ReasonCode, SourceKind
from app.schemas.common import ApiModel


class MetricsTotals(ApiModel):
    requests: int = 0
    avg_latency_ms: float = 0
    p50_latency_ms: float = 0
    p95_latency_ms: float = 0
    tokens: int = 0
    cost_estimate: float = 0
    avg_rating: float | None = None
    feedback_count: int = 0


class MetricsPoint(ApiModel):
    date: dt.date
    requests: int = 0
    p50_latency_ms: float = 0
    p95_latency_ms: float = 0
    tokens: int = 0
    cost_estimate: float = 0


class TopSource(ApiModel):
    document_id: uuid.UUID
    title: str
    source_kind: SourceKind | None
    count: int


class AgentUsage(ApiModel):
    agent_id: uuid.UUID
    name: str
    kind: AgentKind
    requests: int
    avg_latency_ms: float
    avg_tokens: float


class IngestionMetrics(ApiModel):
    documents_by_status: dict[DocumentStatus, int]
    jobs_by_status: dict[JobStatus, int]
    avg_ingest_ms: float = 0


class Metrics(ApiModel):
    totals: MetricsTotals
    series: list[MetricsPoint]
    exclusions_by_reason: dict[ReasonCode, int]
    inclusions_by_type: dict[str, int]
    top_sources: list[TopSource]
    by_agent: list[AgentUsage]
    stage_latency_avg: dict[str, float]
    ingestion: IngestionMetrics
