"""Production readiness — ops workstream (docs/PRODUCTION.md). Owner fills upgrade/downgrade.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
