"""Agent keys attached to a workspace and a project (ADR 001 §7, NOV-112): role, expiry, rotation, inventory.

Defaults are unchanged: a key created the historical way is an ``editor`` key, never expires, and keeps working.
"""

from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update

from app.admin.__main__ import run_keys
from app.config import settings
from app.db import get_sessionmaker, utcnow
from app.models import Agent, AuditLog, Workspace
from tests.conftest import unique

API = "/api/v1/projects"
JSON = dict[str, Any]


async def _create(client: httpx.AsyncClient, slug: str, **extra: Any) -> JSON:
    body = {"name": unique("cle"), "kind": "engineering", "clearance": 1, **extra}
    response = await client.post(f"{API}/{slug}/agents", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _args(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(
        **{"keys_command": "list", "workspace": None, "project": None, "json": True, "dry_run": False, **kw}
    )


async def test_the_historical_creation_is_unchanged(admin_client: httpx.AsyncClient, project: JSON) -> None:
    agent = (await _create(admin_client, project["slug"]))["agent"]
    assert (agent["role"], agent["expires_at"], agent["rotated_at"]) == ("editor", None, None)
    assert agent["clearance"] == 1  # the clearance is a stored, explicit property of the key


async def test_a_viewer_key_reads_but_never_acts_as_an_editor(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[..., httpx.AsyncClient]
) -> None:
    created = await _create(admin_client, project["slug"], role="viewer", clearance=2)
    assert created["agent"]["role"] == "viewer" and created["agent"]["clearance"] == 2
    key = agent_client(created["api_key"])
    seen = await key.get(f"/api/v1/_test/projects/{project['slug']}/viewer")
    assert seen.status_code == 200 and seen.json()["role"] == "viewer"
    assert (await key.post(f"/api/v1/_test/projects/{project['slug']}/editor")).status_code == 403
    refused = await admin_client.post(
        f"{API}/{project['slug']}/agents", json={"name": "x", "role": "owner", "clearance": 1}
    )
    assert refused.status_code == 422  # an agent is never an owner


async def test_an_expired_key_is_refused_and_a_rotation_renews_it(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[..., httpx.AsyncClient]
) -> None:
    slug = project["slug"]
    created = await _create(admin_client, slug, expires_in_days=30)
    agent_id = uuid.UUID(created["agent"]["id"])
    assert created["agent"]["expires_at"] is not None
    first = agent_client(created["api_key"])
    assert (await first.get(f"/api/v1/_test/projects/{slug}/viewer")).status_code == 200
    async with get_sessionmaker()() as session:
        await session.execute(
            update(Agent).where(Agent.id == agent_id).values(expires_at=utcnow() - timedelta(minutes=1))
        )
        await session.commit()
    expired = await first.get(f"/api/v1/_test/projects/{slug}/viewer")
    assert expired.status_code == 401 and "expirée" in expired.json()["detail"]

    rotated = await admin_client.post(f"{API}/{slug}/agents/{agent_id}/rotate", json={"expires_in_days": 90})
    assert rotated.status_code == 200, rotated.text
    new = rotated.json()
    assert new["agent"]["rotated_at"] is not None and new["agent"]["role"] == "editor"
    assert new["agent"]["clearance"] == 1 and new["agent"]["id"] == str(agent_id)
    assert (await first.get(f"/api/v1/_test/projects/{slug}/viewer")).status_code == 401  # old secret is dead
    assert (
        await agent_client(new["api_key"]).get(f"/api/v1/_test/projects/{slug}/viewer")
    ).status_code == 200


async def test_a_rotation_without_body_keeps_the_expiry(
    admin_client: httpx.AsyncClient, project: JSON
) -> None:
    created = await _create(admin_client, project["slug"], expires_in_days=10)
    rotated = await admin_client.post(f"{API}/{project['slug']}/agents/{created['agent']['id']}/rotate")
    assert rotated.status_code == 200
    assert rotated.json()["agent"]["expires_at"] == created["agent"]["expires_at"]


async def test_a_key_stays_attached_to_its_workspace_and_project(
    admin_client: httpx.AsyncClient,
    project: JSON,
    agent_client: Callable[..., httpx.AsyncClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = (await admin_client.post(API, json={"name": f"Projet {unique('b')}"})).json()
    key = agent_client((await _create(admin_client, project["slug"]))["api_key"])
    for mode in ("off", "shadow", "enforce"):
        monkeypatch.setattr(settings, "workspace_enforcement", mode)
        assert (await key.get(f"/api/v1/_test/projects/{other['slug']}/viewer")).status_code == 404, mode
        assert (await key.get(f"/api/v1/_test/projects/{project['slug']}/viewer")).status_code == 200, mode
    async with get_sessionmaker()() as session:  # created through the API: both ids come from the project
        row = await session.scalar(select(Agent).where(Agent.project_id == uuid.UUID(project["id"])))
        assert row is not None and row.workspace_id == settings.default_workspace_id


async def test_an_audit_entry_of_a_key_names_the_key_never_a_user(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[..., httpx.AsyncClient]
) -> None:
    created = await _create(admin_client, project["slug"], name="Agent audité")
    key = agent_client(created["api_key"])
    response = await key.post(
        f"{API}/{project['slug']}/memory",
        json={"scope": "project", "kind": "fact", "title": unique("fait"), "content": "Un fait de l'agent."},
    )
    assert response.status_code == 201, response.text
    async with get_sessionmaker()() as session:
        rows = list(
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.project_id == uuid.UUID(project["id"]), AuditLog.action == "memory.create"
                )
            )
        )
    assert rows and all(r.actor_type == "agent" and r.actor_label == "Agent audité" for r in rows)
    assert all(r.actor_id == uuid.UUID(created["agent"]["id"]) for r in rows)


async def test_the_inventory_lists_keys_without_any_secret(
    admin_client: httpx.AsyncClient, project: JSON, capsys: Any
) -> None:
    created = await _create(admin_client, project["slug"], expires_in_days=5)
    other = await _create(admin_client, project["slug"], role="viewer")
    await admin_client.delete(f"{API}/{project['slug']}/agents/{other['agent']['id']}")
    assert await run_keys(_args(project=project["slug"])) == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert {r["status"] for r in rows} == {"active", "revoked"}
    mine = next(r for r in rows if r["agent_id"] == created["agent"]["id"])
    assert mine["key"].startswith("orb_") and mine["key"].endswith("••••")
    assert (mine["role"], mine["clearance"], mine["project"]) == ("editor", "C1", project["slug"])
    assert mine["age_days"] == 0 and mine["last_used_days_ago"] is None and mine["expires_at"]
    async with get_sessionmaker()() as session:
        hashes = list(await session.scalars(select(Agent.api_key_hash)))
    assert created["api_key"] not in out and all(h not in out for h in hashes)
    assert created["api_key"].split("_")[2] not in out  # not even the secret part
    assert await run_keys(_args(project=project["slug"], json=False)) == 0
    assert "active" in capsys.readouterr().out
    assert await run_keys(_args(workspace="pas-un-uuid")) == 2
    assert (
        await run_keys(_args(workspace=str(uuid.uuid4()))) == 0 and json.loads(capsys.readouterr().out) == []
    )


async def test_a_key_that_left_its_workspace_is_revoked(
    admin_client: httpx.AsyncClient,
    project: JSON,
    agent_client: Callable[..., httpx.AsyncClient],
    capsys: Any,
) -> None:
    created = await _create(admin_client, project["slug"])
    agent_id = uuid.UUID(created["agent"]["id"])
    stray = uuid.uuid4()
    async with get_sessionmaker()() as session:
        session.add(Workspace(id=stray, name="Ailleurs"))
        await session.commit()
        await session.execute(update(Agent).where(Agent.id == agent_id).values(workspace_id=stray))
        await session.commit()
    key = agent_client(created["api_key"])
    assert (
        await key.get(f"/api/v1/_test/projects/{project['slug']}/viewer")
    ).status_code == 200  # off: as before

    assert await run_keys(_args(keys_command="revoke-misplaced", dry_run=True)) == 0
    dry = json.loads(capsys.readouterr().out)
    assert [r["status"] for r in dry] == ["misplaced"]
    async with get_sessionmaker()() as session:
        assert (await session.get(Agent, agent_id)).active is True  # type: ignore[union-attr]  # dry run: no write

    assert await run_keys(_args(keys_command="revoke-misplaced")) == 0
    capsys.readouterr()
    assert (await key.get(f"/api/v1/_test/projects/{project['slug']}/viewer")).status_code == 401
    async with get_sessionmaker()() as session:
        assert (await session.get(Agent, agent_id)).active is False  # type: ignore[union-attr]
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.target_id == str(agent_id), AuditLog.action == "agent.revoke")
        )
    assert audit is not None and audit.details["reason"] == "left_workspace" and audit.actor_type == "system"
    assert (
        await run_keys(_args(keys_command="revoke-misplaced")) == 0
        and json.loads(capsys.readouterr().out) == []
    )
