"""Chantier B — retrieval (docs/AI_CONTEXT_ENGINEERING.md §B1).

* ``chunks.context_preamble``: contextual-retrieval preamble indexed with the chunk (BM25 + embedding);
  NULL = not computed yet (progressive re-index job);
* ``chunks.context_source``: ``llm`` or ``deterministic``;
* partial index on chunks still missing a preamble (progressive re-index cursor).

Downgrade drops exactly these columns and the index.

Revision ID: h002
Revises: h001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h002"
down_revision: str | None = "h001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("context_preamble", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("context_source", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_chunks_context_source"),
        "chunks",
        "context_source IS NULL OR context_source IN ('llm', 'deterministic')",
    )
    op.create_index(
        "ix_chunks_missing_context",
        "chunks",
        ["project_id"],
        postgresql_where=sa.text("context_preamble IS NULL AND status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_missing_context", table_name="chunks")
    op.drop_constraint(op.f("ck_chunks_context_source"), "chunks", type_="check")
    op.drop_column("chunks", "context_source")
    op.drop_column("chunks", "context_preamble")
