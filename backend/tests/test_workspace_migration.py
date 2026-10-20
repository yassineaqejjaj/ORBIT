"""Migration ``h009`` (workspaces, NOV-106) on a **populated** database.

A scratch database is migrated to the schema of ``main`` (``h008``, before this migration), filled with varied
synthetic data (users, projects, members, agent keys, sources, documents, chunks, memory, snapshots, context
requests, webhooks, ...), then: up to ``head`` -> down to ``h008`` -> up again. After every step no row may be
lost or modified outside the new columns (per-table count + content hash that ignores ``workspace_id`` and
``orion_project_id``). Needs the compose Postgres (like the rest of the suite); the database is dropped at the end.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from tests.conftest import BACKEND_DIR, PG_SERVER_URL

MIGRATION_DB = os.environ.get("ORBIT_TEST_MIGRATION_DATABASE", "orbit_mig_nov106")
OLD_HEAD = "h008"
DEFAULT_WORKSPACE_ID = "6f5e1c00-0000-4000-8000-000000000001"
NEW_COLUMNS = ("workspace_id", "orion_project_id")
#: Columns added by h011 (NOV-112) to ``agents`` only: ``role`` exists elsewhere, so it is stripped per table.
EXTRA_NEW_COLUMNS = {
    "agents": ("role", "expires_at", "rotated_at"),
    "users": ("password_login_disabled", "sso_required", "is_break_glass"),  # h012 (NOV-113)
}
OWNING_TABLES = ("users", "projects", "agents", "webhooks")

#: Tables that do not exist before the migration (excluded from the before/after comparison).
NEW_TABLES = {"workspaces", "external_identities"}
SKIPPED_TABLES = {"alembic_version"}


def _id(label: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"orbit-nov106/{label}")


def _alembic(*args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"ORION_DEFAULT_WORKSPACE_ID"}}
    env["ORBIT_DATABASE_URL"] = (
        f"{PG_SERVER_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)}/{MIGRATION_DB}"
    )
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


async def _connect(database: str | None = None) -> asyncpg.Connection:
    return await asyncpg.connect(f"{PG_SERVER_URL}/{database or MIGRATION_DB}", timeout=10)


async def _recreate() -> None:
    conn = await _connect("postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{MIGRATION_DB}"')
    finally:
        await conn.close()


async def _drop() -> None:
    conn = await _connect("postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)')
    finally:
        await conn.close()


def _j(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


async def _populate(conn: asyncpg.Connection) -> None:
    """Varied synthetic data at the ``h008`` schema (no real content, no secret)."""
    users = [
        (_id("u-admin"), "admin@example.test", "Adèle Admin", True, 3),
        (_id("u-alice"), "alice@example.test", "Alice Équipe", False, 2),
        (_id("u-bob"), "bob@example.test", "Bob 'Quote' Ünicode", False, 1),
        (_id("u-carol"), "carol@example.test", "Carol Sans-Projet", False, 0),
    ]
    for uid, email, name, admin, clearance in users:
        await conn.execute(
            "INSERT INTO users (id, email, full_name, password_hash, is_admin, clearance) "
            "VALUES ($1,$2,$3,$4,$5,$6)",
            uid, email, name, "argon2-synthetic-hash", admin, clearance,
        )  # fmt: skip
    projects = []
    for n, (slug, name) in enumerate(
        [("atlas", "Atlas"), ("borealis", "Boréalis"), ("cumulus", "Cumulus"), ("delta-x", "Delta X")]
    ):
        pid = _id(f"p-{slug}")
        projects.append(pid)
        await conn.execute(
            "INSERT INTO projects (id, slug, name, description, settings, created_by) "
            "VALUES ($1,$2,$3,$4,$5::jsonb,$6)",
            pid, slug, name, f"Projet synthétique n°{n} — « accents » & <tags>",
            _j({"default_token_budget": 2000 + 500 * n, "min_relevance": 0.3, "freshness_days": {"note": 90}}),
            users[n % len(users)][0],
        )  # fmt: skip
        for uid, _e, _n, _a, _c in users[:3]:
            await conn.execute(
                "INSERT INTO project_members (project_id, user_id, role) VALUES ($1,$2,$3)",
                pid, uid, ["owner", "editor", "viewer"][(n + users.index((uid, _e, _n, _a, _c))) % 3],
            )  # fmt: skip
    for n, pid in enumerate(projects):
        for k in range(2 if n < 3 else 0):  # the last project has no agent key
            await conn.execute(
                "INSERT INTO agents (id, project_id, name, kind, clearance, api_key_prefix, api_key_hash, active) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                _id(f"a-{n}-{k}"), pid, f"agent-{n}-{k}", ["product", "engineering", "research"][k % 3],
                k + 1, f"pfx{n}{k}", "argon2-synthetic-key-hash", k == 0,
            )  # fmt: skip
        source = _id(f"s-{n}")
        await conn.execute(
            "INSERT INTO sources (id, project_id, name, kind) VALUES ($1,$2,$3,$4)",
            source, pid, f"Source {n}", ["document", "note", "ticket", "url"][n],
        )  # fmt: skip
        for d in range(6):
            doc = _id(f"d-{n}-{d}")
            await conn.execute(
                "INSERT INTO documents (id, project_id, source_id, title, classification, status) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                doc, pid, source, f"Document {n}.{d}", d % 4, "indexed",
            )  # fmt: skip
            await conn.execute(
                "INSERT INTO document_versions (id, document_id, version, content_hash, extracted_text) "
                "VALUES ($1,$2,1,$3,$4)",
                _id(f"dv-{n}-{d}"), doc, f"sha256:{n}{d:02d}", f"Texte synthétique {n}.{d}",
            )  # fmt: skip
            for c in range(4):
                await conn.execute(
                    "INSERT INTO chunks (id, project_id, document_id, version, ordinal, text, text_redacted, "
                    "classification) VALUES ($1,$2,$3,1,$4,$5,$6,$7)",
                    _id(f"c-{n}-{d}-{c}"), pid, doc, c, f"Passage {n}.{d}.{c} café", f"Passage {n}.{d}.{c} café",
                    (d + c) % 4,
                )  # fmt: skip
        kinds = [
            "decision",
            "requirement",
            "constraint",
            "fact",
            "preference",
            "summary",
            "risk",
            "procedure",
        ]
        for m in range(8):
            mem = _id(f"m-{n}-{m}")
            await conn.execute(
                "INSERT INTO memory_items (id, project_id, lineage_id, scope, kind, title, content, status, "
                "classification, tags) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                mem, pid, mem, ["project", "long_term", "project", "user"][m % 4], kinds[m],
                f"Mémoire {n}.{m}", f"Contenu mémoire {n}.{m}", ["validated", "proposed"][m % 2], m % 4,
                [f"t{m}", "synthétique"],
            )  # fmt: skip
            await conn.execute(
                "INSERT INTO memory_events (id, memory_item_id, lineage_id, event, actor_type) "
                "VALUES ($1,$2,$3,'created','system')",
                _id(f"me-{n}-{m}"), mem, mem,
            )  # fmt: skip
            await conn.execute(
                "INSERT INTO memory_provenance (id, memory_item_id) VALUES ($1,$2)", _id(f"mp-{n}-{m}"), mem
            )
        # An organisation-wide long-term item (project_id NULL) exists once.
    org = _id("m-org")
    await conn.execute(
        "INSERT INTO memory_items (id, project_id, lineage_id, scope, kind, title, content) "
        "VALUES ($1,NULL,$1,'long_term','fact','Charte de l''organisation','Mémoire d''organisation synthétique')",
        org,
    )
    for n, pid in enumerate(projects):
        request = _id(f"cr-{n}")
        await conn.execute(
            "INSERT INTO context_requests (id, project_id, trace_id, requested_by_type, task, params) "
            "VALUES ($1,$2,$3,'agent',$4,$5::jsonb)",
            request, pid, f"trace-{n:032d}", f"Tâche synthétique {n}", _j({"cache": {"prefix_hash": f"h{n}"}}),
        )  # fmt: skip
        for k in range(3):
            await conn.execute(
                "INSERT INTO context_decisions (id, request_id, candidate_type, candidate_id, included, reason_code) "
                "VALUES ($1,$2,'chunk',$3,$4,$5)",
                _id(f"cd-{n}-{k}"), request, str(_id(f"c-{n}-0-{k}")), k != 2,
                "INCLUDED_RELEVANT" if k != 2 else "EXCLUDED_ACL",
            )  # fmt: skip
        for v in (1, 2):
            await conn.execute(
                "INSERT INTO context_snapshots (id, project_id, request_id, name, version, task, content, "
                "content_hash, created_by_type, items) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'agent',$9::jsonb)",
                _id(f"cs-{n}-{v}"), pid, request, "discovery", v, f"Tâche {n}", f"[S1] contenu {n}.{v}",
                f"sha256:{n}{v}", _j([{"key": f"chunk:{_id(f'c-{n}-0-0')}", "citation": "S1"}]),
            )  # fmt: skip
        if n < 3:
            hook = _id(f"w-{n}")
            await conn.execute(
                "INSERT INTO webhooks (id, project_id, url, secret_encrypted) VALUES ($1,$2,$3,'fernet-synthetic')",
                hook, pid, f"https://hooks.example.test/{n}",
            )  # fmt: skip
            event = _id(f"ce-{n}")
            await conn.execute(
                "INSERT INTO change_events (id, project_id, type, title) VALUES ($1,$2,'memory.created',$3)",
                event, pid, f"Événement {n}",
            )  # fmt: skip
            await conn.execute(
                "INSERT INTO webhook_deliveries (id, webhook_id, project_id, change_event_id, event_type, payload) "
                "VALUES ($1,$2,$3,$4,'memory.created',$5::jsonb)",
                _id(f"wd-{n}"), hook, pid, event, _j({"project": {"slug": f"p{n}"}}),
            )  # fmt: skip
        await conn.execute(
            "INSERT INTO relations (id, project_id, src_type, src_id, rel_type, dst_type, dst_id) "
            "VALUES ($1,$2,'memory',$3,'relates_to','memory',$4)",
            _id(f"r-{n}"), pid, _id(f"m-{n}-0"), _id(f"m-{n}-1"),
        )  # fmt: skip
        await conn.execute(
            "INSERT INTO entities (id, project_id, name) VALUES ($1,$2,$3)",
            _id(f"en-{n}"),
            pid,
            f"Entité {n}",
        )
        await conn.execute(
            "INSERT INTO ingestion_jobs (id, project_id, kind) VALUES ($1,$2,'ingest')", _id(f"j-{n}"), pid
        )
        await conn.execute(
            "INSERT INTO audit_log (id, project_id, actor_type, action, summary) "
            "VALUES ($1,$2,'user','project.create',$3)",
            _id(f"al-{n}"), pid, f"Création {n}",
        )  # fmt: skip


_FINGERPRINT_SQL = """
SELECT count(*) AS n,
       coalesce(md5(string_agg(h, ',' ORDER BY h)), '') AS digest
FROM (SELECT md5((to_jsonb(t) {strip})::text) AS h FROM {table} t) rows
"""


async def _fingerprint(conn: asyncpg.Connection) -> dict[str, tuple[int, str]]:
    """``{table: (row count, content hash ignoring the new columns)}`` for every table of the schema."""
    tables = [
        r["table_name"]
        for r in await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
            "AND table_type='BASE TABLE' ORDER BY table_name"
        )
        if r["table_name"] not in NEW_TABLES | SKIPPED_TABLES
    ]
    result: dict[str, tuple[int, str]] = {}
    for table in tables:
        strip = "".join(f" - '{col}'" for col in (*NEW_COLUMNS, *EXTRA_NEW_COLUMNS.get(table, ())))
        row = await conn.fetchrow(_FINGERPRINT_SQL.format(table=f'"{table}"', strip=strip))
        assert row is not None
        result[table] = (int(row["n"]), str(row["digest"]))
    return result


async def _columns(conn: asyncpg.Connection, table: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=$1",
        table,
    )
    return {r["column_name"] for r in rows}


async def _tables(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    return {r["table_name"] for r in rows}


async def _assert_migrated(conn: asyncpg.Connection, default_id: str = DEFAULT_WORKSPACE_ID) -> None:
    workspaces = await conn.fetch("SELECT id::text AS id, name FROM workspaces")
    assert [w["id"] for w in workspaces] == [default_id]
    for table in OWNING_TABLES:
        total = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
        in_default = await conn.fetchval(
            f'SELECT count(*) FROM "{table}" WHERE workspace_id = $1::uuid', default_id
        )
        assert total == in_default, table
        nullable = await conn.fetchval(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name=$1 AND column_name='workspace_id'",
            table,
        )
        assert nullable == "NO", table
    assert (
        await conn.fetchval("SELECT count(*) FROM projects WHERE orion_project_id IS DISTINCT FROM id") == 0
    )
    assert await conn.fetchval(
        "SELECT count(DISTINCT orion_project_id) FROM projects"
    ) == await conn.fetchval("SELECT count(*) FROM projects")


async def _insert_identity(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "INSERT INTO external_identities (id, user_id, workspace_id, issuer, subject, email, linked_by) "
        "VALUES ($1, $2, $3::uuid, 'https://idp.example.test/realms/orion', 'sub-1', 'a@example.test', 'confirmed')",
        _id("identity"),
        _id("u-alice"),
        DEFAULT_WORKSPACE_ID,
    )


async def _step(coro_factory: Any) -> Any:
    conn = await _connect()
    try:
        return await coro_factory(conn)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def scratch_database() -> Iterator[None]:
    asyncio.run(_recreate())
    yield
    asyncio.run(_drop())


def test_the_migration_is_additive_and_reversible_on_a_populated_database(
    scratch_database: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _alembic("heads").stdout.count("(head)") == 1, "the migration history must keep a single head"

    _alembic("upgrade", OLD_HEAD)  # schema of main
    asyncio.run(_step(_populate))
    before = asyncio.run(_step(_fingerprint))
    assert before["users"][0] == 4 and before["projects"][0] == 4 and before["agents"][0] == 6
    assert before["chunks"][0] == 96 and before["memory_items"][0] == 33 and before["webhooks"][0] == 3
    assert all(count > 0 for table, (count, _) in before.items() if table in OWNING_TABLES)
    assert "workspaces" not in asyncio.run(_step(_tables))

    _alembic("upgrade", "head")
    after_up = asyncio.run(_step(_fingerprint))
    asyncio.run(_step(_assert_migrated))
    assert after_up == before, "rows lost or modified by the upgrade"
    tables_up = asyncio.run(_step(_tables))
    assert "workspaces" in tables_up
    assert "h012 (head)" in _alembic("current").stdout
    _alembic("check")  # the models and the migrated schema agree

    # h010 (NOV-109) adds a table only: dropping it again changes no existing row, and an upgrade re-creates it empty
    asyncio.run(_step(_insert_identity))
    _alembic("downgrade", "h009")
    assert asyncio.run(_step(_fingerprint)) == before, "rows lost or modified by the h010 downgrade"
    assert "external_identities" not in asyncio.run(_step(_tables))
    assert "workspaces" in asyncio.run(_step(_tables))
    _alembic("upgrade", "head")
    assert asyncio.run(_step(_fingerprint)) == before, "rows lost or modified by the h010 upgrade"
    assert asyncio.run(_step(lambda c: c.fetchval("SELECT count(*) FROM external_identities"))) == 0

    # h011 (NOV-112): three columns on agents; every pre-existing key reads role=editor, no expiry, never rotated
    keys = asyncio.run(_step(lambda c: c.fetch("SELECT role, expires_at, rotated_at FROM agents")))
    assert len(keys) == 6 and {(k["role"], k["expires_at"], k["rotated_at"]) for k in keys} == {
        ("editor", None, None)
    }
    _alembic("downgrade", "h010")
    assert asyncio.run(_step(_fingerprint)) == before, "rows lost or modified by the h011 downgrade"
    assert asyncio.run(_step(lambda c: _columns(c, "agents"))).isdisjoint(
        {"role", "expires_at", "rotated_at"}
    )
    _alembic("upgrade", "head")
    assert asyncio.run(_step(_fingerprint)) == before, "rows lost or modified by the h011 upgrade"

    # h012 (NOV-113): three flags on users, all false for every pre-existing account; downgrade drops them
    flags = asyncio.run(
        _step(lambda c: c.fetch("SELECT password_login_disabled, sso_required, is_break_glass FROM users"))
    )
    assert len(flags) == 4 and {tuple(f.values()) for f in flags} == {(False, False, False)}
    _alembic("downgrade", "h011")
    assert asyncio.run(_step(_fingerprint)) == before, "rows lost or modified by the h012 downgrade"
    assert asyncio.run(_step(lambda c: _columns(c, "users"))).isdisjoint(
        {"password_login_disabled", "sso_required", "is_break_glass"}
    )
    _alembic("upgrade", "head")
    assert asyncio.run(_step(_fingerprint)) == before, "rows lost or modified by the h012 upgrade"

    _alembic("downgrade", OLD_HEAD)
    after_down = asyncio.run(_step(_fingerprint))
    assert after_down == before, "rows lost or modified by the downgrade"
    assert "workspaces" not in asyncio.run(_step(_tables))
    for table in OWNING_TABLES:
        assert "workspace_id" not in asyncio.run(_step(lambda c, t=table: _columns(c, t)))
    assert "orion_project_id" not in asyncio.run(_step(lambda c: _columns(c, "projects")))

    _alembic("upgrade", "head")
    after_again = asyncio.run(_step(_fingerprint))
    asyncio.run(_step(_assert_migrated))
    assert after_again == before, "rows lost or modified by the second upgrade"

    with capsys.disabled():
        print("\n[NOV-106] populated-database migration: table: rows (identical before / up / down / up)")
        for table, (count, digest) in sorted(before.items()):
            print(f"  {table:24s} {count:5d}  {digest[:12]}")
        print(f"  total rows: {sum(c for c, _ in before.values())}")


def test_the_default_workspace_id_comes_from_the_environment() -> None:
    custom = "0a0a0a0a-0000-4000-8000-00000000abcd"
    asyncio.run(_recreate())
    try:
        _alembic("upgrade", OLD_HEAD)

        async def _one(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO users (id, email, full_name, password_hash) VALUES ($1,'x@example.test','X','h')",
                _id("custom-user"),
            )
            await conn.execute(
                "INSERT INTO projects (id, slug, name) VALUES ($1,'custom','Custom')", _id("custom-p")
            )

        asyncio.run(_step(_one))
        _alembic("upgrade", "head", extra_env={"ORION_DEFAULT_WORKSPACE_ID": custom})
        asyncio.run(_step(lambda c: _assert_migrated(c, default_id=custom)))
    finally:
        asyncio.run(_drop())
