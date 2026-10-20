"""ORION — external (OIDC) identities (ADR 001 §8, NOV-109).

New table only (``external_identities``): nothing existing is touched, so the upgrade cannot lose or modify a row.
Downgrade drops the table (the links are lost; accounts, passwords and keys are unaffected).

Revision ID: h010
Revises: h009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h010"
down_revision: str | None = "h009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("linked_by", sa.Text(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_external_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_external_identities_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_identities")),
    )
    op.create_index(
        "uq_external_identities_issuer_subject", "external_identities", ["issuer", "subject"], unique=True
    )
    op.create_index(
        "uq_external_identities_user_id_issuer", "external_identities", ["user_id", "issuer"], unique=True
    )
    op.create_index(op.f("ix_external_identities_workspace_id"), "external_identities", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("external_identities")
