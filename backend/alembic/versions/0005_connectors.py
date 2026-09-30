"""Production readiness — connectors workstream (docs/PRODUCTION.md). Owner fills upgrade/downgrade.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
