"""ORION — account migration flags (ADR 001 §8, NOV-113).

Additive: three boolean columns on ``users`` (all ``false``: every account behaves exactly as before), a rule that a
break-glass account is an administrator that is never forced out of the password, and at most one such account.
Downgrade drops them (a flagged account recovers password login, the safe direction).

Revision ID: h012
Revises: h011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h012"
down_revision: str | None = "h011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FLAGS = ("password_login_disabled", "sso_required", "is_break_glass")


def upgrade() -> None:
    for name in _FLAGS:
        op.add_column("users", sa.Column(name, sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.create_check_constraint(
        op.f("ck_users_break_glass_rules"),
        "users",
        "NOT is_break_glass OR (is_admin AND NOT password_login_disabled AND NOT sso_required)",
    )
    op.create_index(
        "uq_users_break_glass", "users", ["is_break_glass"], unique=True, postgresql_where=sa.text("is_break_glass")
    )


def downgrade() -> None:
    op.drop_index("uq_users_break_glass", table_name="users", postgresql_where=sa.text("is_break_glass"))
    op.drop_constraint(op.f("ck_users_break_glass_rules"), "users", type_="check")
    for name in reversed(_FLAGS):
        op.drop_column("users", name)
