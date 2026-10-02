"""Product features — features_triage_feed (docs/FEATURES.md). Owner fills upgrade/downgrade.

Revision ID: f001
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

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
    # F1/F2 tables are added below by the feature owner.


def downgrade() -> None:
    # F1/F2 tables are dropped above by the feature owner.
    op.execute("DELETE FROM ingestion_jobs WHERE kind IN ('webhook', 'connector_sync')")
    op.drop_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", f"kind IN {_OLD_KINDS}")
