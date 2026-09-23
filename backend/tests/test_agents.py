"""Agents: key issuance (shown once), authentication, scoping, rotation and revocation."""

from __future__ import annotations

import re

import httpx

API_KEY_PATTERN = re.compile(r"^orb_[a-z0-9]{8}_[A-Za-z0-9]{32}$")


async def _create_agent(client: httpx.AsyncClient, slug: str, **payload: object) -> dict:  # type: ignore[type-arg]
    body = {"name": "Agent produit", "kind": "product", "description": "Rédige les specs", "clearance": 2}
    body.update(payload)
    response = await client.post(f"/api/v1/projects/{slug}/agents", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_agent_returns_key_once(admin_client: httpx.AsyncClient, project: dict) -> None:  # type: ignore[type-arg]
    created = await _create_agent(admin_client, project["slug"])
    key = created["api_key"]
    assert API_KEY_PATTERN.match(key)
    agent = created["agent"]
    assert agent["api_key_prefix"] == key.split("_")[1]
    assert agent["active"] is True
    assert agent["kind"] == "product"
    assert agent["clearance"] == 2
    assert agent["last_used_at"] is None

    listed = await admin_client.get(f"/api/v1/projects/{project['slug']}/agents")
    assert listed.status_code == 200
    assert all("api_key" not in a for a in listed.json())
    assert key not in listed.text


async def test_agent_key_authentication(
    admin_client: httpx.AsyncClient,
    project: dict,
    agent_client,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    slug = project["slug"]
    created = await _create_agent(admin_client, slug)
    key = created["api_key"]

    for header in ("authorization", "x-orbit-key"):
        c = agent_client(key, header=header)
        response = await c.get(f"/api/v1/_test/projects/{slug}/viewer")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["kind"] == "agent"
        assert body["role"] == "editor"
        assert body["clearance"] == 2
        assert body["principals"] == ["project:*"]
        assert (await c.post(f"/api/v1/_test/projects/{slug}/editor")).status_code == 200

    c = agent_client(key)
    owner_only = await c.post(f"/api/v1/_test/projects/{slug}/owner")
    assert owner_only.status_code == 403
    user_only = await c.get(f"/api/v1/projects/{slug}")
    assert user_only.status_code == 403
    assert user_only.json()["detail"] == "Cette opération n'est pas accessible avec une clé d'agent"

    agents = (await admin_client.get(f"/api/v1/projects/{slug}/agents")).json()
    assert next(a for a in agents if a["id"] == created["agent"]["id"])["last_used_at"] is not None


async def test_agent_is_scoped_to_its_project(
    admin_client: httpx.AsyncClient,
    project: dict,
    agent_client,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    key = (await _create_agent(admin_client, project["slug"]))["api_key"]
    other = (await admin_client.post("/api/v1/projects", json={"name": "Autre projet"})).json()
    response = await agent_client(key).get(f"/api/v1/_test/projects/{other['slug']}/viewer")
    assert response.status_code == 404


async def test_invalid_keys_are_rejected(client: httpx.AsyncClient, project: dict) -> None:  # type: ignore[type-arg]
    slug = project["slug"]
    for key in ("orb_invalid", "orb_abcdefgh_" + "A" * 32):
        response = await client.get(f"/api/v1/_test/projects/{slug}/viewer", headers={"X-Orbit-Key": key})
        assert response.status_code == 401
        assert response.json() == {"detail": "Clé d'agent invalide", "code": "unauthorized"}


async def test_rotate_and_revoke(
    admin_client: httpx.AsyncClient,
    project: dict,
    agent_client,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    slug = project["slug"]
    created = await _create_agent(admin_client, slug, name="Agent design", kind="design", clearance=1)
    agent_id = created["agent"]["id"]
    old_key = created["api_key"]

    rotated = await admin_client.post(f"/api/v1/projects/{slug}/agents/{agent_id}/rotate")
    assert rotated.status_code == 200
    new_key = rotated.json()["api_key"]
    assert new_key != old_key
    assert rotated.json()["agent"]["api_key_prefix"] == new_key.split("_")[1]
    assert (await agent_client(old_key).get(f"/api/v1/_test/projects/{slug}/viewer")).status_code == 401
    assert (await agent_client(new_key).get(f"/api/v1/_test/projects/{slug}/viewer")).status_code == 200

    revoked = await admin_client.delete(f"/api/v1/projects/{slug}/agents/{agent_id}")
    assert revoked.status_code == 204
    denied = await agent_client(new_key).get(f"/api/v1/_test/projects/{slug}/viewer")
    assert denied.status_code == 401
    assert denied.json()["detail"] == "Clé d'agent révoquée"
    listed = (await admin_client.get(f"/api/v1/projects/{slug}/agents")).json()
    assert next(a for a in listed if a["id"] == agent_id)["active"] is False
    assert (await admin_client.post(f"/api/v1/projects/{slug}/agents/{agent_id}/rotate")).status_code == 409
    assert (await admin_client.delete(f"/api/v1/projects/{slug}/agents/{agent_id}")).status_code == 204


async def test_agent_clearance_cannot_exceed_creator(
    make_user,
    client_for,  # type: ignore[no-untyped-def]
) -> None:
    owner = await make_user(clearance=1)
    c = await client_for(owner)
    project = (await c.post("/api/v1/projects", json={"name": "Projet C1"})).json()
    response = await c.post(
        f"/api/v1/projects/{project['slug']}/agents", json={"name": "Agent", "kind": "custom", "clearance": 3}
    )
    assert response.status_code == 403
    assert "C3" in response.json()["detail"]
    ok = await c.post(
        f"/api/v1/projects/{project['slug']}/agents", json={"name": "Agent", "kind": "custom", "clearance": 1}
    )
    assert ok.status_code == 201


async def test_agent_management_requires_owner(
    admin_client: httpx.AsyncClient,
    project: dict,
    make_user,
    client_for,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    editor = await make_user()
    await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": editor.email, "role": "editor"}
    )
    c = await client_for(editor)
    assert (await c.get(f"/api/v1/projects/{project['slug']}/agents")).status_code == 200
    response = await c.post(
        f"/api/v1/projects/{project['slug']}/agents", json={"name": "X", "kind": "custom", "clearance": 1}
    )
    assert response.status_code == 403


async def test_member_principals(
    admin_client: httpx.AsyncClient,
    project: dict,
    make_user,
    client_for,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    editor = await make_user()
    await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": editor.email, "role": "editor"}
    )
    c = await client_for(editor)
    body = (await c.get(f"/api/v1/_test/projects/{project['slug']}/viewer")).json()
    assert body["kind"] == "user"
    assert body["principals"] == sorted(["project:*", "role:viewer", "role:editor", f"user:{editor.id}"])
