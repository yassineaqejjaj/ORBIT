"""Chantier A — AI security (docs/AI_CONTEXT_ENGINEERING.md §A).

* ``chunks``: prompt-injection score / reasons and quarantine (``quarantined``, release date and owner);
* ``sources.trust`` (``high`` / ``medium`` / ``low``, NULL = default of the source kind);
* ``context_decisions.reason_code`` accepts ``EXCLUDED_QUARANTINE``.

Downgrade drops exactly these columns, the partial index and the CHECK constraint, and restores the
previous reason-code constraint (decisions recorded with ``EXCLUDED_QUARANTINE`` are deleted first).

Revision ID: h001
Revises: f004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h001"
down_revision: str | None = "f004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_REASONS = (
    "INCLUDED_RELEVANT",
    "INCLUDED_PINNED",
    "EXCLUDED_ACL",
    "EXCLUDED_CLASSIFICATION",
    "EXCLUDED_SCOPE",
    "EXCLUDED_STALE",
    "EXCLUDED_EXPIRED",
    "EXCLUDED_SUPERSEDED",
    "EXCLUDED_CONFLICT",
    "EXCLUDED_DUPLICATE",
    "EXCLUDED_LOW_SCORE",
    "EXCLUDED_BUDGET",
    "EXCLUDED_FORGOTTEN",
)
_NEW_REASONS = (*_OLD_REASONS, "EXCLUDED_QUARANTINE")


def _reasons(values: tuple[str, ...]) -> str:
    return "reason_code IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("chunks", sa.Column("injection_score", sa.Float(), server_default=sa.text("0"), nullable=False))
    op.add_column(
        "chunks",
        sa.Column(
            "injection_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("chunks", sa.Column("quarantined", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("chunks", sa.Column("quarantine_released_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chunks", sa.Column("quarantine_released_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_chunks_quarantine_released_by_users"),
        "chunks",
        "users",
        ["quarantine_released_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chunks_project_id_quarantined",
        "chunks",
        ["project_id"],
        postgresql_where=sa.text("quarantined"),
    )
    op.add_column("sources", sa.Column("trust", sa.Text(), nullable=True))
    op.create_check_constraint(op.f("ck_sources_trust"), "sources", "trust IN ('high', 'medium', 'low')")
    op.drop_constraint(op.f("ck_context_decisions_reason_code"), "context_decisions", type_="check")
    op.create_check_constraint(
        op.f("ck_context_decisions_reason_code"), "context_decisions", _reasons(_NEW_REASONS)
    )


def downgrade() -> None:
    op.execute("DELETE FROM context_decisions WHERE reason_code = 'EXCLUDED_QUARANTINE'")
    op.drop_constraint(op.f("ck_context_decisions_reason_code"), "context_decisions", type_="check")
    op.create_check_constraint(
        op.f("ck_context_decisions_reason_code"), "context_decisions", _reasons(_OLD_REASONS)
    )
    op.drop_constraint(op.f("ck_sources_trust"), "sources", type_="check")
    op.drop_column("sources", "trust")
    op.drop_index("ix_chunks_project_id_quarantined", table_name="chunks")
    op.drop_constraint(op.f("fk_chunks_quarantine_released_by_users"), "chunks", type_="foreignkey")
    op.drop_column("chunks", "quarantine_released_by")
    op.drop_column("chunks", "quarantine_released_at")
    op.drop_column("chunks", "quarantined")
    op.drop_column("chunks", "injection_reasons")
    op.drop_column("chunks", "injection_score")
