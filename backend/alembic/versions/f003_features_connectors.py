"""Product features — features_connectors (docs/FEATURES.md). Owner fills upgrade/downgrade.

Revision ID: f003
Revises: f002
"""

from collections.abc import Sequence

revision: str = "f003"
down_revision: str | None = "f002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
