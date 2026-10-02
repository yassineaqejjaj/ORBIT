"""Product features F1/F2 — triage & change feed (docs/FEATURES.md): change events, subscriptions,
webhooks + deliveries, conflict resolutions; new job kinds.

Revision ID: f001
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f001"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_KINDS = "('ingest', 'reindex', 'forget', 'consolidate', 'extract_memory')"
_NEW_KINDS = "('ingest', 'reindex', 'forget', 'consolidate', 'extract_memory', 'webhook', 'connector_sync')"


def upgrade() -> None:
    # New job kinds: webhook deliveries (F2) and connector syncs (F5).
    op.drop_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", f"kind IN {_NEW_KINDS}")
    _ts = {"server_default": sa.text("now()"), "nullable": False}
    _acl = postgresql.ARRAY(sa.Text())
    op.create_table(
        "change_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("target_type", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("classification", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("acl_principals", _acl, server_default=sa.text("ARRAY['project:*']::text[]"), nullable=False),
        sa.Column("actor_label", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **_ts),
        sa.CheckConstraint("classification BETWEEN 0 AND 3", name=op.f("ck_change_events_classification_range")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_change_events_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_change_events")),
    )
    op.create_index("ix_change_events_project_id_created_at", "change_events", ["project_id", sa.text("created_at DESC")])
    op.create_index("ix_change_events_project_id_type", "change_events", ["project_id", "type"])
    op.create_index("ix_change_events_target_id", "change_events", ["target_id"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("digest", sa.Text(), server_default=sa.text("'off'"), nullable=False),
        sa.Column("types", _acl, server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_ts),
        sa.CheckConstraint("digest IN ('off', 'daily', 'weekly')", name=op.f("ck_subscriptions_digest")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_subscriptions_project_id_projects"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_subscriptions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index("uq_subscriptions_project_id_user_id", "subscriptions", ["project_id", "user_id"], unique=True)

    op.create_table(
        "webhooks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("types", _acl, server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("disabled_reason", sa.Text(), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_ts),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_webhooks_project_id_projects"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_webhooks_created_by_id_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhooks")),
    )
    op.create_index("ix_webhooks_project_id", "webhooks", ["project_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("webhook_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("change_event_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.REAL(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_ts),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'skipped')", name=op.f("ck_webhook_deliveries_status")),
        sa.ForeignKeyConstraint(["webhook_id"], ["webhooks.id"], name=op.f("fk_webhook_deliveries_webhook_id_webhooks"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_webhook_deliveries_project_id_projects"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["change_event_id"], ["change_events.id"], name=op.f("fk_webhook_deliveries_change_event_id_change_events"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index("ix_webhook_deliveries_webhook_id_created_at", "webhook_deliveries", ["webhook_id", sa.text("created_at DESC")])

    op.create_table(
        "conflict_resolutions",
        sa.Column("relation_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("a_id", sa.UUID(), nullable=False),
        sa.Column("b_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("winner_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("similarity", sa.REAL(), server_default=sa.text("0"), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by_label", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("resolved_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_ts),
        sa.CheckConstraint("status IN ('resolved', 'dismissed')", name=op.f("ck_conflict_resolutions_status")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=op.f("fk_conflict_resolutions_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("relation_id", name=op.f("pk_conflict_resolutions")),
    )
    op.create_index("ix_conflict_resolutions_project_id_created_at", "conflict_resolutions", ["project_id", sa.text("created_at DESC")])


def downgrade() -> None:
    for table in ("conflict_resolutions", "webhook_deliveries", "webhooks", "subscriptions", "change_events"):
        op.drop_table(table)
    op.execute("DELETE FROM ingestion_jobs WHERE kind IN ('webhook', 'connector_sync')")
    op.drop_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", f"kind IN {_OLD_KINDS}")
