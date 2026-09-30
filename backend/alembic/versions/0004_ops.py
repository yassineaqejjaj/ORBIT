"""Production readiness — ops workstream (docs/PRODUCTION.md §3 « Exploitation »).

* ``ingestion_jobs``: ``priority``, ``crash_count`` (poison-pill detection), ``cancel_requested_at``,
  ``trace_parent``; statuses ``dead`` (dead letter) and ``cancelled``; ``project_id`` nullable
  (platform-wide reindex jobs); partial index for the fair claim;
* ``worker_heartbeats``: one row per worker process (``/ops/status``);
* ``scheduled_tasks``: last run of cluster-wide singleton tasks (maintenance, retention, drift).

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = "status IN ('queued', 'running', 'succeeded', 'failed')"
_NEW_STATUSES = "status IN ('queued', 'running', 'succeeded', 'failed', 'dead', 'cancelled')"


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column(
        "ingestion_jobs", sa.Column("crash_count", sa.Integer(), server_default=sa.text("0"), nullable=False)
    )
    op.add_column("ingestion_jobs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("trace_parent", sa.Text(), nullable=True))
    op.alter_column("ingestion_jobs", "project_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint(op.f("ck_ingestion_jobs_status"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_status"), "ingestion_jobs", _NEW_STATUSES)
    op.create_index(
        "ix_ingestion_jobs_queued_fair",
        "ingestion_jobs",
        ["project_id", sa.text("priority DESC"), "run_after", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("hostname", sa.Text(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("in_flight", sa.Integer(), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("stopping", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_worker_heartbeats")),
    )
    op.create_table(
        "scheduled_tasks",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.Text(), server_default=sa.text("'never'"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "last_summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("holder", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_scheduled_tasks")),
    )


def downgrade() -> None:
    op.drop_table("scheduled_tasks")
    op.drop_table("worker_heartbeats")
    op.drop_index("ix_ingestion_jobs_queued_fair", table_name="ingestion_jobs")
    # Rows that the previous schema cannot represent: terminal dead/cancelled become failed and
    # platform-wide jobs (no project) are removed.
    op.execute("UPDATE ingestion_jobs SET status = 'failed' WHERE status IN ('dead', 'cancelled')")
    op.execute("DELETE FROM ingestion_jobs WHERE project_id IS NULL")
    op.drop_constraint(op.f("ck_ingestion_jobs_status"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_status"), "ingestion_jobs", _OLD_STATUSES)
    op.alter_column("ingestion_jobs", "project_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("ingestion_jobs", "trace_parent")
    op.drop_column("ingestion_jobs", "cancel_requested_at")
    op.drop_column("ingestion_jobs", "crash_count")
    op.drop_column("ingestion_jobs", "priority")
