"""ORION — workspace entity and aligned project id (ADR 001 §5, NOV-106).

Additive and reversible:

* table ``workspaces`` and the **default workspace** (``ORION_DEFAULT_WORKSPACE_ID``, else the documented
  constant ``6f5e1c00-0000-4000-8000-000000000001``) inserted by this migration;
* ``workspace_id`` (NOT NULL, ``DEFAULT <default workspace>``, FK, index) on ``users``, ``projects``,
  ``agents`` and ``webhooks``. A constant default makes PostgreSQL add the column without rewriting any row:
  existing rows read the default, their content is untouched;
* ``projects.orion_project_id`` (UUID, NOT NULL, unique) backfilled with the project's own ``id`` (stable,
  deterministic, equal to the id NOVA already stores in its project reference); the slug stays an alias.

Documents, chunks, memory, snapshots, context requests and the OpenSearch indices get **no** column: they
inherit their workspace through their project, so nothing is reindexed.

Downgrade drops the new columns, indexes, foreign keys and the ``workspaces`` table (the workspace
assignment of rows is lost, every row keeps its other data); upgrade again re-attaches everything to the
default workspace.

Revision ID: h009
Revises: h008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.config import settings

revision: str = "h009"
down_revision: str | None = "h008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNING_TABLES = ("users", "projects", "agents", "webhooks")


def upgrade() -> None:
    default_id = str(settings.default_workspace_id)
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
    )
    op.execute(
        sa.text("INSERT INTO workspaces (id, name) VALUES (CAST(:id AS uuid), :name)").bindparams(
            id=default_id, name="Espace par défaut"
        )
    )
    for table in _OWNING_TABLES:
        op.add_column(
            table,
            sa.Column(
                "workspace_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text(f"'{default_id}'::uuid"),
            ),
        )
        op.create_foreign_key(
            op.f(f"fk_{table}_workspace_id_workspaces"),
            table,
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(op.f(f"ix_{table}_workspace_id"), table, ["workspace_id"])

    op.add_column("projects", sa.Column("orion_project_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("UPDATE projects SET orion_project_id = id")
    op.alter_column("projects", "orion_project_id", nullable=False)
    op.create_index("uq_projects_orion_project_id", "projects", ["orion_project_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_projects_orion_project_id", table_name="projects")
    op.drop_column("projects", "orion_project_id")
    for table in reversed(_OWNING_TABLES):
        op.drop_index(op.f(f"ix_{table}_workspace_id"), table_name=table)
        op.drop_constraint(op.f(f"fk_{table}_workspace_id_workspaces"), table, type_="foreignkey")
        op.drop_column(table, "workspace_id")
    op.drop_table("workspaces")
