"""Chantier E tables (docs/AI_CONTEXT_ENGINEERING.md §E): evaluation bench, ranking weight log,
LLM-judge verdicts and A2A handoffs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, Boolean, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)


class EvalSet(UUIDPkMixin, TimestampMixin, Base):
    """§E1 golden set of a project (reference questions + expected items)."""

    __tablename__ = "eval_sets"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_eval_sets_project_id_name"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class EvalCase(UUIDPkMixin, CreatedAtMixin, Base):
    """One reference question; ``expected`` = ``[{"type": "memory"|"document", "id", "title"}]``."""

    __tablename__ = "eval_cases"
    __table_args__ = (Index("ix_eval_cases_set_id", "set_id"),)

    set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    origin: Mapped[str] = mapped_column(
        Text, nullable=False, default="manual", server_default=text("'manual'")
    )


class EvalRun(UUIDPkMixin, CreatedAtMixin, Base):
    """One execution of a golden set: aggregated metrics, per-question details, pass/fail."""

    __tablename__ = "eval_runs"
    __table_args__ = (Index("ix_eval_runs_project_id_created_at", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="queued", server_default=text("'queued'")
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False, default="ui", server_default=text("'ui'"))
    k: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default=text("5"))
    min_recall: Mapped[float | None] = mapped_column(REAL, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    cases: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RankingWeightChange(UUIDPkMixin, CreatedAtMixin, Base):
    """§E2 journal of the per-project ranking weights: the latest row's ``after`` is in force."""

    __tablename__ = "ranking_weight_changes"
    __table_args__ = (Index("ix_ranking_weight_changes_project_id_created_at", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    reason: Mapped[str] = mapped_column(Text, nullable=False)  # learn | revert | reset
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    reverts_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ranking_weight_changes.id", ondelete="SET NULL"), nullable=True
    )
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_label: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))


class ContextJudgement(UUIDPkMixin, CreatedAtMixin, Base):
    """§E3 LLM-judge verdict on a served context (``method``: llm | skipped_guardrail | heuristic)."""

    __tablename__ = "context_judgements"
    __table_args__ = (
        Index("ix_context_judgements_project_id_created_at", "project_id", "created_at"),
        UniqueConstraint("request_id", name="uq_context_judgements_request_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_requests.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(REAL, nullable=True)
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    model: Mapped[str | None] = mapped_column(Text, nullable=True)


class A2AHandoff(UUIDPkMixin, CreatedAtMixin, Base):
    """§E5 signed snapshot handoff; ``jti`` is unique (replay protection), ``received_at`` once used."""

    __tablename__ = "a2a_handoffs"
    __table_args__ = (UniqueConstraint("jti", name="uq_a2a_handoffs_jti"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    jti: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("context_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_by: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["A2AHandoff", "ContextJudgement", "EvalCase", "EvalRun", "EvalSet", "RankingWeightChange"]
