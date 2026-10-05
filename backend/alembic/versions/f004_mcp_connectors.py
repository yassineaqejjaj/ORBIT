"""Product feature F6 — MCP connectors (docs/FEATURES.md): connector type ``mcp``.

The preset (Atlassian, Microsoft 365, Google Workspace, Slack, GitHub, Linear, Obsidian, custom) is stored
in ``connectors.config.preset``; only the ``type`` CHECK constraint changes.

Downgrade restores the F5 constraint exactly; MCP connectors (and their runs) are deleted first since they
would violate it (documents already synchronised are kept, like when a connector is deleted).

Revision ID: f004
Revises: f003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f004"
down_revision: str | None = "f003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = "('sharepoint', 'confluence', 'jira')"
_NEW_TYPES = "('sharepoint', 'confluence', 'jira', 'mcp')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_connectors_type"), "connectors", type_="check")
    op.create_check_constraint(op.f("ck_connectors_type"), "connectors", f"type IN {_NEW_TYPES}")


def downgrade() -> None:
    op.execute(
        "DELETE FROM connector_runs WHERE connector_id IN (SELECT id FROM connectors WHERE type = 'mcp')"
    )
    op.execute("DELETE FROM connectors WHERE type = 'mcp'")
    op.drop_constraint(op.f("ck_connectors_type"), "connectors", type_="check")
    op.create_check_constraint(op.f("ck_connectors_type"), "connectors", f"type IN {_OLD_TYPES}")
