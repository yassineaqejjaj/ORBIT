"""Chantier D — memory (docs/AI_CONTEXT_ENGINEERING.md §D).

* memory kind ``procedure`` (§D1 skills) + ``memory_items.skill_meta`` (SKILL.md metadata);
* ``relations.method`` / ``relations.explanation`` (§D3 model-based contradiction detection);
* ``entities`` / ``entity_aliases`` (§D2 entity resolution, audited merge/unmerge);
* job kind ``reflect`` (§D4 monthly « ce qui a changé » reflection).

Downgrade restores the previous schema exactly: procedure items and reflect jobs are deleted first (they
would violate the restored CHECK constraints), then the tables and columns are dropped.

Revision ID: h004
Revises: h002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h004"
down_revision: str | None = "h002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_OLD_MEMORY_KINDS = "('decision', 'requirement', 'constraint', 'fact', 'preference', 'summary', 'risk')"
_NEW_MEMORY_KINDS = (
    "('decision', 'requirement', 'constraint', 'fact', 'preference', 'summary', 'risk', 'procedure')"
)
_OLD_JOB_KINDS = "('ingest', 'reindex', 'forget', 'consolidate', 'extract_memory', 'webhook', 'connector_sync')"
_NEW_JOB_KINDS = (
    "('ingest', 'reindex', 'forget', 'consolidate', 'extract_memory', 'webhook', 'connector_sync', 'reflect')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_memory_items_kind"), "memory_items", type_="check")
    op.create_check_constraint(op.f("ck_memory_items_kind"), "memory_items", f"kind IN {_NEW_MEMORY_KINDS}")
    op.add_column("memory_items", sa.Column("skill_meta", postgresql.JSONB(), nullable=True))
    op.add_column("relations", sa.Column("method", sa.Text(), nullable=True))
    op.add_column("relations", sa.Column("explanation", sa.Text(), nullable=True))
    op.drop_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", f"kind IN {_NEW_JOB_KINDS}")

    op.create_table(
        "entities",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'concept'")),
        sa.Column("merged_into_id", _UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_entities_project_id_projects"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"],
            ["entities.id"],
            name=op.f("fk_entities_merged_into_id_entities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
    )
    op.create_index("ix_entities_project_id", "entities", ["project_id"])
    op.create_table(
        "entity_aliases",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("project_id", _UUID, nullable=False),
        sa.Column("entity_id", _UUID, nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("normalized", sa.Text(), nullable=False),
        sa.Column("merged_from_id", _UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_entity_aliases_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], name=op.f("fk_entity_aliases_entity_id_entities"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["merged_from_id"],
            ["entities.id"],
            name=op.f("fk_entity_aliases_merged_from_id_entities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_aliases")),
    )
    op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])
    op.create_index("ix_entity_aliases_project_id_normalized", "entity_aliases", ["project_id", "normalized"])


def downgrade() -> None:
    op.drop_index("ix_entity_aliases_project_id_normalized", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_entity_id", table_name="entity_aliases")
    op.drop_table("entity_aliases")
    op.drop_index("ix_entities_project_id", table_name="entities")
    op.drop_table("entities")
    op.execute("DELETE FROM ingestion_jobs WHERE kind = 'reflect'")
    op.drop_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", f"kind IN {_OLD_JOB_KINDS}")
    op.drop_column("relations", "explanation")
    op.drop_column("relations", "method")
    op.drop_column("memory_items", "skill_meta")
    op.execute("DELETE FROM memory_items WHERE kind = 'procedure'")
    op.drop_constraint(op.f("ck_memory_items_kind"), "memory_items", type_="check")
    op.create_check_constraint(op.f("ck_memory_items_kind"), "memory_items", f"kind IN {_OLD_MEMORY_KINDS}")
