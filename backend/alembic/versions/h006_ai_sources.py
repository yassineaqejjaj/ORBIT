"""Chantier F — sources (docs/AI_CONTEXT_ENGINEERING.md §F).

* memory kind ``action`` (§F1 meeting action items) + ``memory_items.action_meta`` (owner, due date,
  speaker, timestamp).

Meetings themselves need no schema change: a meeting is a document whose ``metadata.meeting`` carries the
date, participants, speakers and turn timeline; project e-mails and Figma files are MCP connector presets.

Downgrade restores the previous schema exactly: action items are deleted first (they would violate the
restored CHECK constraint), then the column is dropped.

Revision ID: h006
Revises: h005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h006"
down_revision: str | None = "h005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_MEMORY_KINDS = (
    "('decision', 'requirement', 'constraint', 'fact', 'preference', 'summary', 'risk', 'procedure')"
)
_NEW_MEMORY_KINDS = (
    "('decision', 'requirement', 'constraint', 'fact', 'preference', 'summary', 'risk', 'procedure', "
    "'action')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_memory_items_kind"), "memory_items", type_="check")
    op.create_check_constraint(op.f("ck_memory_items_kind"), "memory_items", f"kind IN {_NEW_MEMORY_KINDS}")
    op.add_column("memory_items", sa.Column("action_meta", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("memory_items", "action_meta")
    op.execute("DELETE FROM memory_items WHERE kind = 'action'")
    op.drop_constraint(op.f("ck_memory_items_kind"), "memory_items", type_="check")
    op.create_check_constraint(op.f("ck_memory_items_kind"), "memory_items", f"kind IN {_OLD_MEMORY_KINDS}")
