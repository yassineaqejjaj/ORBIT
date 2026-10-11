"""ORION — validated learnings (docs/AI_CONTEXT_ENGINEERING.md).

* memory kind ``learning`` + ``memory_items.learning_meta`` (where the learning applies, and the evidence that
  verified it: experiment, runs, baseline and candidate scores).

Downgrade restores the previous schema exactly: learnings are deleted first (they would violate the restored
CHECK constraint), then the column is dropped.

Revision ID: h008
Revises: h007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h008"
down_revision: str | None = "h007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_MEMORY_KINDS = (
    "('decision', 'requirement', 'constraint', 'fact', 'preference', 'summary', 'risk', 'procedure', "
    "'action')"
)
_NEW_MEMORY_KINDS = (
    "('decision', 'requirement', 'constraint', 'fact', 'preference', 'summary', 'risk', 'procedure', "
    "'action', 'learning')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_memory_items_kind"), "memory_items", type_="check")
    op.create_check_constraint(op.f("ck_memory_items_kind"), "memory_items", f"kind IN {_NEW_MEMORY_KINDS}")
    op.add_column("memory_items", sa.Column("learning_meta", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("memory_items", "learning_meta")
    op.execute("DELETE FROM memory_items WHERE kind = 'learning'")
    op.drop_constraint(op.f("ck_memory_items_kind"), "memory_items", type_="check")
    op.create_check_constraint(op.f("ck_memory_items_kind"), "memory_items", f"kind IN {_OLD_MEMORY_KINDS}")
