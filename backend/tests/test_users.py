"""Platform user administration."""

from __future__ import annotations

import httpx

from tests.conftest import unique


async def test_admin_creates_lists_and_updates_users(admin_client: httpx.AsyncClient) -> None:
    email = f"{unique('claire')}@Devoteam.com"
    created = await admin_client.post(
        "/api/v1/users",
        json={"email": email, "full_name": "Claire Martin", "password": "Mot-de-passe-123", "clearance": 2},
    )
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["email"] == email.lower()
    assert user["clearance"] == 2
    assert user["is_admin"] is False
    assert user["avatar_color"].startswith("#")

    duplicate = await admin_client.post(
        "/api/v1/users",
        json={"email": email.upper(), "full_name": "Autre", "password": "Mot-de-passe-123"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "conflict"

    listed = await admin_client.get("/api/v1/users", params={"q": "claire"})
    assert listed.status_code == 200
    assert any(u["id"] == user["id"] for u in listed.json())

    patched = await admin_client.patch(
        f"/api/v1/users/{user['id']}", json={"clearance": 3, "full_name": "Claire M."}
    )
    assert patched.status_code == 200
    assert patched.json()["clearance"] == 3
    assert patched.json()["full_name"] == "Claire M."

    login = await admin_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Mot-de-passe-123"}
    )
    assert login.status_code == 200


async def test_user_validation(admin_client: httpx.AsyncClient) -> None:
    bad = await admin_client.post(
        "/api/v1/users", json={"email": "pas-un-email", "full_name": "X", "password": "court", "clearance": 7}
    )
    assert bad.status_code == 422
    fields = {e["field"] for e in bad.json()["errors"]}
    assert {"email", "password", "clearance"} <= fields


async def test_user_admin_is_forbidden_to_non_admins(make_user, client_for) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    c = await client_for(user)
    for response in (
        await c.get("/api/v1/users"),
        await c.post(
            "/api/v1/users", json={"email": "x@example.com", "full_name": "X", "password": "Mot-de-passe-1"}
        ),
        await c.patch(f"/api/v1/users/{user.id}", json={"is_admin": True}),
    ):
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"


async def test_update_unknown_user(admin_client: httpx.AsyncClient) -> None:
    response = await admin_client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000", json={"clearance": 1}
    )
    assert response.status_code == 404
