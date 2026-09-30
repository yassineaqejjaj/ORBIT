"""Production readiness — identity workstream (docs/PRODUCTION.md). Owner fills upgrade/downgrade.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
