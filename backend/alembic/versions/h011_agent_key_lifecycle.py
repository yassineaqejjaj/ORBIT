"""ORION — lifecycle of agent keys (ADR 001 §7, NOV-112): explicit role, optional expiry, rotation date.

Additive: three columns on ``agents``. ``role`` defaults to ``editor`` (the level every key had), ``expires_at`` and
``rotated_at`` are NULL: existing keys keep working exactly as before. Downgrade drops the columns (a ``viewer``
key would come back as ``editor`` after a later upgrade: re-create such keys, or revoke them before downgrading).

Revision ID: h011
Revises: h010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h011"
down_revision: str | None = "h010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("role", sa.Text(), server_default=sa.text("'editor'"), nullable=False))
    op.add_column("agents", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f("ck_agents_role"), "agents", "role IN ('viewer', 'editor')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_agents_role"), "agents", type_="check")
    op.drop_column("agents", "rotated_at")
    op.drop_column("agents", "expires_at")
    op.drop_column("agents", "role")
