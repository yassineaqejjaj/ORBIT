"""Product features — F3/F4 (docs/FEATURES.md): memory-card columns, Ask conversations, integrations.

Revision ID: f002
Revises: f001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f002"
down_revision: str | None = "f001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_EMPTY_LIST = sa.text("'[]'::jsonb")


def _timestamps(updated: bool = True) -> list[sa.Column]:
    columns = [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))
    ]
    if updated:
        columns.append(
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
            )
        )
    return columns


def upgrade() -> None:
    # F3 — memory-card fields of LLM-assisted extraction.
    for column in ("rationale", "decided_by", "confidence_reason"):
        op.add_column("memory_items", sa.Column(column, sa.Text(), nullable=True))

    # F4 — « Demander à ORBIT ».
    op.create_table(
        "ask_conversations",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=True),
        sa.Column("agent_id", _UUID, nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False, server_default=sa.text("'web'")),
        *_timestamps(),
        sa.CheckConstraint("channel IN ('web', 'teams', 'api')", name=op.f("ck_ask_conversations_channel")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_ask_conversations_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ask_conversations_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("fk_ask_conversations_agent_id_agents"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ask_conversations")),
    )
    op.create_index(
        "ix_ask_conversations_project_user",
        "ask_conversations",
        ["project_id", "user_id", sa.text("updated_at DESC")],
    )
    op.create_index("ix_ask_conversations_project_agent", "ask_conversations", ["project_id", "agent_id"])

    op.create_table(
        "ask_messages",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("conversation_id", _UUID, nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("request_id", _UUID, nullable=True),
        sa.Column("mode", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=False, server_default=_EMPTY_LIST),
        sa.Column("follow_ups", postgresql.JSONB(), nullable=False, server_default=_EMPTY_LIST),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=_EMPTY_LIST),
        sa.Column("llm_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("feedback_id", _UUID, nullable=True),
        *_timestamps(updated=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_ask_messages_role")),
        sa.CheckConstraint(
            "mode IS NULL OR mode IN ('llm', 'extractive')", name=op.f("ck_ask_messages_mode")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('high', 'medium', 'low')",
            name=op.f("ck_ask_messages_confidence"),
        ),
        sa.CheckConstraint("rating IS NULL OR rating IN (1, 5)", name=op.f("ck_ask_messages_rating")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ask_conversations.id"],
            name=op.f("fk_ask_messages_conversation_id_ask_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["context_requests.id"],
            name=op.f("fk_ask_messages_request_id_context_requests"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["context_feedback.id"],
            name=op.f("fk_ask_messages_feedback_id_context_feedback"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ask_messages")),
    )
    op.create_index("ix_ask_messages_conversation_created", "ask_messages", ["conversation_id", "created_at"])
    op.create_index("ix_ask_messages_request_id", "ask_messages", ["request_id"])
    op.create_index(
        "uq_ask_messages_external_id",
        "ask_messages",
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "integrations",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_id", _UUID, nullable=True),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('teams')", name=op.f("ck_integrations_kind")),
        sa.UniqueConstraint("project_id", "kind", name="uq_integrations_project_kind"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_integrations_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_integrations_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
    )


def downgrade() -> None:
    op.drop_table("integrations")
    op.drop_index("uq_ask_messages_external_id", table_name="ask_messages")
    op.drop_index("ix_ask_messages_request_id", table_name="ask_messages")
    op.drop_index("ix_ask_messages_conversation_created", table_name="ask_messages")
    op.drop_table("ask_messages")
    op.drop_index("ix_ask_conversations_project_agent", table_name="ask_conversations")
    op.drop_index("ix_ask_conversations_project_user", table_name="ask_conversations")
    op.drop_table("ask_conversations")
    for column in ("confidence_reason", "decided_by", "rationale"):
        op.drop_column("memory_items", column)
