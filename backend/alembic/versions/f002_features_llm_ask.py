"""Product features — features_llm_ask (docs/FEATURES.md). Owner fills upgrade/downgrade.

Revision ID: f002
Revises: f001
"""

from collections.abc import Sequence

revision: str = "f002"
down_revision: str | None = "f001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
