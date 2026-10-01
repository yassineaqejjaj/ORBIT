"""Identity workstream (docs/PRODUCTION.md): server-side sessions, agent delegations, invitations,
user lifecycle/MFA/OIDC columns and agent key lifecycle (expiry, scopes, rotation grace).

Revision ID: 0002
Revises: 0001
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Frozen copy of app.identity.scopes.DEFAULT_SCOPES at the time of this migration.
DEFAULT_SCOPES_JSON = json.dumps(
    ["context:read", "search:read", "snapshots:read", "memory:propose", "sessions:write", "feedback:write"]
)


def upgrade() -> None:
    op.create_table(
        "user_invitations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("clearance", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("invited_by", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("clearance BETWEEN 0 AND 3", name=op.f("ck_user_invitations_clearance_range")),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_user_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_invitations_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_invitations")),
    )
    op.create_index("uq_user_invitations_token_hash", "user_invitations", ["token_hash"], unique=True)
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("auth_method", sa.Text(), server_default=sa.text("'password'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
    )
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"], unique=False)
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)
    op.create_table(
        "agent_delegations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("granted_by", sa.UUID(), nullable=True),
        sa.Column("max_classification", sa.SmallInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "max_classification IS NULL OR (max_classification BETWEEN 0 AND 3)",
            name=op.f("ck_agent_delegations_max_classification_range"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_agent_delegations_agent_id_agents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_agent_delegations_granted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_agent_delegations_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_delegations_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_delegations")),
    )
    op.create_index("ix_agent_delegations_project_id", "agent_delegations", ["project_id"], unique=False)
    op.create_index("ix_agent_delegations_user_id", "agent_delegations", ["user_id"], unique=False)
    op.create_index(
        "uq_agent_delegations_active",
        "agent_delegations",
        ["agent_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.add_column("agents", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("agents", sa.Column("previous_key_prefix", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("previous_key_hash", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("previous_key_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_agents_previous_key_prefix",
        "agents",
        ["previous_key_prefix"],
        unique=True,
        postgresql_where=sa.text("previous_key_prefix IS NOT NULL"),
    )
    op.add_column(
        "users", sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False)
    )
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("auth_provider", sa.Text(), server_default=sa.text("'local'"), nullable=False)
    )
    op.add_column("users", sa.Column("oidc_subject", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column("users", sa.Column("mfa_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("mfa_pending_secret", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "mfa_recovery_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("mfa_last_step", sa.BigInteger(), nullable=True))
    op.create_index(
        "uq_users_oidc_subject",
        "users",
        ["oidc_subject"],
        unique=True,
        postgresql_where=sa.text("oidc_subject IS NOT NULL"),
    )
    op.create_check_constraint(op.f("ck_users_auth_provider"), "users", "auth_provider IN ('local', 'oidc')")
    # Existing agent keys get the default lifetime and scopes (docs/PRODUCTION.md §3).
    op.execute(
        "UPDATE agents SET expires_at = now() + interval '180 days', "
        "scopes = '" + DEFAULT_SCOPES_JSON + "'::jsonb"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_auth_provider"), "users", type_="check")
    op.drop_index(
        "uq_users_oidc_subject", table_name="users", postgresql_where=sa.text("oidc_subject IS NOT NULL")
    )
    op.drop_column("users", "mfa_last_step")
    op.drop_column("users", "mfa_recovery_codes")
    op.drop_column("users", "mfa_pending_secret")
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "oidc_subject")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "deactivated_at")
    op.drop_column("users", "is_active")
    op.drop_index(
        "uq_agents_previous_key_prefix",
        table_name="agents",
        postgresql_where=sa.text("previous_key_prefix IS NOT NULL"),
    )
    op.drop_column("agents", "previous_key_expires_at")
    op.drop_column("agents", "previous_key_hash")
    op.drop_column("agents", "previous_key_prefix")
    op.drop_column("agents", "scopes")
    op.drop_column("agents", "expires_at")
    op.drop_index(
        "uq_agent_delegations_active",
        table_name="agent_delegations",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index("ix_agent_delegations_user_id", table_name="agent_delegations")
    op.drop_index("ix_agent_delegations_project_id", table_name="agent_delegations")
    op.drop_table("agent_delegations")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("uq_user_invitations_token_hash", table_name="user_invitations")
    op.drop_table("user_invitations")
