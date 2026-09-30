"""Production readiness — compliance workstream (docs/PRODUCTION.md). Owner fills upgrade/downgrade.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
