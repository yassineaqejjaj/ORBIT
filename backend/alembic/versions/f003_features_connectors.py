"""Product feature F5 — connectors (docs/FEATURES.md): ``connectors`` and ``connector_runs``.

Revision ID: f003
Revises: f002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f003"
down_revision: str | None = "f002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TYPES = "('sharepoint', 'confluence', 'jira')"
_STATUSES = "('idle', 'syncing', 'ok', 'error', 'paused')"
_RUN_STATUSES = "('queued', 'running', 'succeeded', 'partial', 'failed')"
_TRIGGERS = "('manual', 'schedule', 'initial')"


def upgrade() -> None:
    _ts = {"server_default": sa.text("now()"), "nullable": False}
    _json = postgresql.JSONB(astext_type=sa.Text())
    _zero = {"server_default": sa.text("0"), "nullable": False}
    op.create_table(
        "connectors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config", _json, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("secret_hint", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("schedule_minutes", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'idle'"), nullable=False),
        sa.Column("default_classification", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("restrict_to_editors", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("cursor", _json, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_ts),
        sa.CheckConstraint(f"type IN {_TYPES}", name=op.f("ck_connectors_type")),
        sa.CheckConstraint(f"status IN {_STATUSES}", name=op.f("ck_connectors_status")),
        sa.CheckConstraint(
            "default_classification BETWEEN 0 AND 3", name=op.f("ck_connectors_default_classification_range")
        ),
        sa.CheckConstraint("schedule_minutes >= 0", name=op.f("ck_connectors_schedule_minutes_positive")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_connectors_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name=op.f("fk_connectors_source_id_sources"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_connectors_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connectors")),
    )
    op.create_index("ix_connectors_project_id", "connectors", ["project_id"])

    op.create_table(
        "connector_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("connector_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("trigger", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.REAL(), nullable=True),
        sa.Column("fetched", sa.Integer(), **_zero),
        sa.Column("created", sa.Integer(), **_zero),
        sa.Column("updated", sa.Integer(), **_zero),
        sa.Column("unchanged", sa.Integer(), **_zero),
        sa.Column("skipped", sa.Integer(), **_zero),
        sa.Column("forgotten", sa.Integer(), **_zero),
        sa.Column("errors", sa.Integer(), **_zero),
        sa.Column("progress", _json, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_samples", _json, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_ts),
        sa.CheckConstraint(f"status IN {_RUN_STATUSES}", name=op.f("ck_connector_runs_status")),
        sa.CheckConstraint(f"trigger IN {_TRIGGERS}", name=op.f("ck_connector_runs_trigger")),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["connectors.id"],
            name=op.f("fk_connector_runs_connector_id_connectors"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_connector_runs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_runs")),
    )
    op.create_index(
        "ix_connector_runs_connector_id_created_at",
        "connector_runs",
        ["connector_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("connector_runs")
    op.drop_table("connectors")
