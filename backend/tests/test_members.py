"""Project members and the last-owner rule."""

from __future__ import annotations

import httpx


async def test_member_lifecycle(admin_client: httpx.AsyncClient, project: dict, make_user) -> None:  # type: ignore[no-untyped-def,type-arg]
    base = f"/api/v1/projects/{project['slug']}/members"
    user = await make_user()

    added = await admin_client.post(base, json={"email": user.email.upper(), "role": "editor"})
    assert added.status_code == 201, added.text
    member = added.json()
    assert member["role"] == "editor"
    assert member["user"]["email"] == user.email

    duplicate = await admin_client.post(base, json={"email": user.email, "role": "viewer"})
    assert duplicate.status_code == 409

    unknown = await admin_client.post(base, json={"email": "inconnu@example.com", "role": "viewer"})
    assert unknown.status_code == 404

    listed = (await admin_client.get(base)).json()
    assert {m["user"]["email"]: m["role"] for m in listed}[user.email] == "editor"

    promoted = await admin_client.patch(f"{base}/{user.id}", json={"role": "owner"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "owner"

    removed = await admin_client.delete(f"{base}/{user.id}")
    assert removed.status_code == 204
    assert all(m["user"]["id"] != str(user.id) for m in (await admin_client.get(base)).json())
    assert (await admin_client.delete(f"{base}/{user.id}")).status_code == 404


async def test_last_owner_cannot_be_removed_or_demoted(
    make_user,
    client_for,  # type: ignore[no-untyped-def]
) -> None:
    owner = await make_user()
    c = await client_for(owner)
    project = (await c.post("/api/v1/projects", json={"name": "Projet solo"})).json()
    base = f"/api/v1/projects/{project['slug']}/members"

    demote = await c.patch(f"{base}/{owner.id}", json={"role": "editor"})
    assert demote.status_code == 409
    assert demote.json()["detail"] == "Impossible de retirer le dernier propriétaire du projet"
    remove = await c.delete(f"{base}/{owner.id}")
    assert remove.status_code == 409

    second = await make_user()
    assert (await c.post(base, json={"email": second.email, "role": "owner"})).status_code == 201
    assert (await c.patch(f"{base}/{owner.id}", json={"role": "viewer"})).status_code == 200


async def test_only_owners_manage_members(
    admin_client: httpx.AsyncClient,
    project: dict,
    make_user,
    client_for,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    base = f"/api/v1/projects/{project['slug']}/members"
    editor = await make_user()
    await admin_client.post(base, json={"email": editor.email, "role": "editor"})
    c = await client_for(editor)
    assert (await c.get(base)).status_code == 200
    target = await make_user()
    response = await c.post(base, json={"email": target.email, "role": "viewer"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Action réservée aux propriétaires du projet"
