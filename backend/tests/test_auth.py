"""Login, session cookie, bearer JWT, logout."""

from __future__ import annotations

import httpx

from app.security import create_access_token
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


async def test_login_sets_http_only_cookie(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["is_admin"] is True
    assert body["clearance"] == 3
    assert "password_hash" not in body
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("orbit_session=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie or "samesite=lax" in cookie.lower()
    assert "Secure" not in cookie

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["id"]


async def test_login_is_case_insensitive_on_email(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL.upper(), "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200


async def test_login_failure(client: httpx.AsyncClient) -> None:
    for payload in (
        {"email": ADMIN_EMAIL, "password": "wrong-password"},
        {"email": "nobody@example.com", "password": "whatever"},
    ):
        response = await client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == 401
        assert response.json() == {"detail": "E-mail ou mot de passe incorrect", "code": "unauthorized"}
        assert "set-cookie" not in response.headers


async def test_me_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_bearer_jwt_is_accepted(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
    token = login.cookies.get("orbit_session")
    assert token
    client.cookies.clear()
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == user.email


async def test_invalid_and_orphan_tokens(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert response.status_code == 401
    import uuid

    orphan = create_access_token(uuid.uuid4())
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {orphan}"})
    assert response.status_code == 401


async def test_logout_clears_cookie(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert (
        'orbit_session=""' in response.headers["set-cookie"] or "Max-Age=0" in response.headers["set-cookie"]
    )
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_password_change_revokes_sessions(
    admin_client: httpx.AsyncClient, make_user, client_for
) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    user_client = await client_for(user)
    assert (await user_client.get("/api/v1/auth/me")).status_code == 200
    response = await admin_client.patch(
        f"/api/v1/users/{user.id}", json={"password": "Nouveau-mot-de-passe-1"}
    )
    assert response.status_code == 200
    revoked = await user_client.get("/api/v1/auth/me")
    assert revoked.status_code == 401
    assert "révoquée" in revoked.json()["detail"]


async def test_login_is_audited(admin_client: httpx.AsyncClient, db_session) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from app.models import AuditLog

    rows = (
        await db_session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "auth.login")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    ).all()
    assert rows and rows[0].project_id is None


async def test_login_without_remember_sets_session_cookie(client: httpx.AsyncClient) -> None:
    """« Rester connecté » décoché : cookie de session sans Max-Age (supprimé à la fermeture du navigateur)."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@orbit.local", "password": "orbit-admin", "remember": False},
    )
    assert response.status_code == 200
    header = response.headers.get("set-cookie", "").lower()
    assert "orbit_session=" in header
    assert "max-age" not in header

    persistent = await client.post(
        "/api/v1/auth/login", json={"email": "admin@orbit.local", "password": "orbit-admin"}
    )
    assert "max-age" in persistent.headers.get("set-cookie", "").lower()


async def test_new_user_starts_not_onboarded_and_can_complete(client_for, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    c = await client_for(user)

    me = await c.get("/api/v1/auth/me")
    assert me.json()["onboarding_completed_at"] is None

    done = await c.post("/api/v1/auth/me/onboarding/complete")
    assert done.status_code == 200
    first = done.json()["onboarding_completed_at"]
    assert first is not None

    # Idempotent: a second completion keeps the first date.
    again = await c.post("/api/v1/auth/me/onboarding/complete")
    assert again.json()["onboarding_completed_at"] == first
    assert (await c.get("/api/v1/auth/me")).json()["onboarding_completed_at"] == first


async def test_onboarding_can_be_restarted(client_for, make_user) -> None:  # type: ignore[no-untyped-def]
    c = await client_for(await make_user())
    await c.post("/api/v1/auth/me/onboarding/complete")

    restarted = await c.post("/api/v1/auth/me/onboarding/restart")
    assert restarted.status_code == 200
    assert restarted.json()["onboarding_completed_at"] is None
    assert (await c.get("/api/v1/auth/me")).json()["onboarding_completed_at"] is None


async def test_onboarding_requires_authentication(client: httpx.AsyncClient) -> None:
    for action in ("complete", "restart"):
        response = await client.post(f"/api/v1/auth/me/onboarding/{action}")
        assert response.status_code == 401
