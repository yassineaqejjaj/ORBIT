"""Onboarding des nouveaux comptes.

* ``users.onboarding_completed_at`` : NULL tant que l'utilisateur n'a pas terminé (ou passé) la visite de
  première connexion. Les comptes existants sont marqués comme déjà intégrés : seuls les comptes créés après
  cette migration voient la visite.

Revision ID: h007
Revises: h006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h007"
down_revision: str | None = "h006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET onboarding_completed_at = now()")


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed_at")
