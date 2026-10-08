"""Chantier E — evaluation & interoperability (docs/AI_CONTEXT_ENGINEERING.md §E).

* ``eval_sets`` / ``eval_cases`` / ``eval_runs`` (§E1 evaluation bench);
* ``ranking_weight_changes`` (§E2 bounded, logged, reversible ranking weights per project);
* ``context_judgements`` (§E3 LLM judge on a sample of served contexts);
* ``a2a_handoffs`` (§E5 signed snapshot handoffs, replay protection);
* job kinds ``evaluate`` and ``judge``.

Downgrade restores the previous schema exactly: evaluate/judge jobs are deleted first (they would violate
the restored CHECK constraint), then the tables are dropped.

Revision ID: h005
Revises: h004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h005"
down_revision: str | None = "h004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()
_OLD_JOB_KINDS = (
    "('ingest', 'reindex', 'forget', 'consolidate', 'extract_memory', 'webhook', 'connector_sync', 'reflect')"
)
_NEW_JOB_KINDS = (
    "('ingest', 'reindex', 'forget', 'consolidate', 'extract_memory', 'webhook', 'connector_sync', "
    "'reflect', 'evaluate', 'judge')"
)


def _id() -> sa.Column:
    return sa.Column("id", _UUID, nullable=False)


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def _project(table: str) -> list:
    return [
        sa.Column("project_id", _UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f(f"fk_{table}_project_id_projects"), ondelete="CASCADE"
        ),
    ]


def _json(name: str, default: str) -> sa.Column:
    return sa.Column(name, _JSONB, nullable=False, server_default=sa.text(f"'{default}'::jsonb"))


def upgrade() -> None:
    op.drop_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", f"kind IN {_NEW_JOB_KINDS}")

    op.create_table(
        "eval_sets",
        _id(),
        *_project("eval_sets"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_by", _UUID, nullable=True),
        _created(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_sets")),
        sa.UniqueConstraint("project_id", "name", name="uq_eval_sets_project_id_name"),
    )
    op.create_table(
        "eval_cases",
        _id(),
        sa.Column("set_id", _UUID, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        _json("expected", "[]"),
        sa.Column("origin", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        _created(),
        sa.ForeignKeyConstraint(
            ["set_id"], ["eval_sets.id"], name=op.f("fk_eval_cases_set_id_eval_sets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_cases")),
    )
    op.create_index("ix_eval_cases_set_id", "eval_cases", ["set_id"])
    op.create_table(
        "eval_runs",
        _id(),
        *_project("eval_runs"),
        sa.Column("set_id", _UUID, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("trigger", sa.Text(), nullable=False, server_default=sa.text("'ui'")),
        sa.Column("k", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("min_recall", sa.REAL(), nullable=True),
        _json("metrics", "{}"),
        _json("cases", "[]"),
        _json("config", "{}"),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("job_id", _UUID, nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(
            ["set_id"], ["eval_sets.id"], name=op.f("fk_eval_runs_set_id_eval_sets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_index("ix_eval_runs_project_id_created_at", "eval_runs", ["project_id", "created_at"])
    op.create_table(
        "ranking_weight_changes",
        _id(),
        *_project("ranking_weight_changes"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before", _JSONB, nullable=False),
        sa.Column("after", _JSONB, nullable=False),
        _json("signals", "{}"),
        sa.Column("reverts_id", _UUID, nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_label", sa.Text(), nullable=False, server_default=sa.text("''")),
        _created(),
        sa.ForeignKeyConstraint(
            ["reverts_id"],
            ["ranking_weight_changes.id"],
            name=op.f("fk_ranking_weight_changes_reverts_id_ranking_weight_changes"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ranking_weight_changes")),
    )
    op.create_index(
        "ix_ranking_weight_changes_project_id_created_at",
        "ranking_weight_changes",
        ["project_id", "created_at"],
    )
    op.create_table(
        "context_judgements",
        _id(),
        *_project("context_judgements"),
        sa.Column("request_id", _UUID, nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("score", sa.REAL(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("model", sa.Text(), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["context_requests.id"],
            name=op.f("fk_context_judgements_request_id_context_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_context_judgements")),
        sa.UniqueConstraint("request_id", name="uq_context_judgements_request_id"),
    )
    op.create_index(
        "ix_context_judgements_project_id_created_at", "context_judgements", ["project_id", "created_at"]
    )
    op.create_table(
        "a2a_handoffs",
        _id(),
        *_project("a2a_handoffs"),
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("snapshot_id", _UUID, nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_by", sa.Text(), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["context_snapshots.id"],
            name=op.f("fk_a2a_handoffs_snapshot_id_context_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_a2a_handoffs")),
        sa.UniqueConstraint("jti", name="uq_a2a_handoffs_jti"),
    )


def downgrade() -> None:
    op.drop_table("a2a_handoffs")
    op.drop_index("ix_context_judgements_project_id_created_at", table_name="context_judgements")
    op.drop_table("context_judgements")
    op.drop_index("ix_ranking_weight_changes_project_id_created_at", table_name="ranking_weight_changes")
    op.drop_table("ranking_weight_changes")
    op.drop_index("ix_eval_runs_project_id_created_at", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_cases_set_id", table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_table("eval_sets")
    op.execute("DELETE FROM ingestion_jobs WHERE kind IN ('evaluate', 'judge')")
    op.drop_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", type_="check")
    op.create_check_constraint(op.f("ck_ingestion_jobs_kind"), "ingestion_jobs", f"kind IN {_OLD_JOB_KINDS}")
