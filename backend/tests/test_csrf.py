"""CSRF double submit (signed, bound to the session) and Origin/Referer checks."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.security import new_csrf_token
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, unique

PROJECT_BODY = {"name": "Projet CSRF", "description": "test"}


@pytest_asyncio.fixture
async def raw_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Client that does NOT echo the CSRF cookie automatically (unlike the conftest clients)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def _login(c: httpx.AsyncClient) -> str:
    response = await c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    token = c.cookies.get("orbit_csrf")
    assert token
    return token


def _project() -> dict[str, str]:
    return {**PROJECT_BODY, "name": f"Projet {unique('csrf')}"}


async def test_cookie_session_requires_the_csrf_header(raw_client: httpx.AsyncClient) -> None:
    token = await _login(raw_client)
    missing = await raw_client.post("/api/v1/projects", json=_project())
    assert missing.status_code == 403
    assert missing.json()["code"] == "csrf_failed"
    wrong = await raw_client.post("/api/v1/projects", json=_project(), headers={"X-CSRF-Token": token + "x"})
    assert wrong.status_code == 403
    ok = await raw_client.post("/api/v1/projects", json=_project(), headers={"X-CSRF-Token": token})
    assert ok.status_code == 201, ok.text
    # Safe methods never need it.
    assert (await raw_client.get("/api/v1/projects")).status_code == 200


async def test_token_must_be_bound_to_the_current_session(raw_client: httpx.AsyncClient) -> None:
    await _login(raw_client)
    anonymous = new_csrf_token("")  # validly signed, but not for this session
    raw_client.cookies.set("orbit_csrf", anonymous)
    response = await raw_client.post("/api/v1/projects", json=_project(), headers={"X-CSRF-Token": anonymous})
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


async def test_csrf_endpoint_returns_the_session_token(raw_client: httpx.AsyncClient) -> None:
    anonymous = await raw_client.get("/api/v1/auth/csrf")
    assert anonymous.status_code == 200
    assert anonymous.json()["csrf_token"] == raw_client.cookies.get("orbit_csrf")
    login_token = await _login(raw_client)
    assert login_token != anonymous.json()["csrf_token"]
    current = await raw_client.get("/api/v1/auth/csrf")
    assert current.json()["csrf_token"] == login_token
    cookie_header = current.headers["set-cookie"]
    assert "orbit_csrf=" in cookie_header and "httponly" not in cookie_header.lower()
    response = await raw_client.post(
        "/api/v1/projects", json=_project(), headers={"X-CSRF-Token": current.json()["csrf_token"]}
    )
    assert response.status_code == 201


async def test_bearer_and_agent_key_calls_are_exempt(raw_client: httpx.AsyncClient) -> None:
    await _login(raw_client)
    jwt_token = raw_client.cookies.get("orbit_session")
    raw_client.cookies.clear()
    response = await raw_client.post(
        "/api/v1/projects", json=_project(), headers={"Authorization": f"Bearer {jwt_token}"}
    )
    assert response.status_code == 201, response.text


async def test_agent_key_is_exempt(admin_client: httpx.AsyncClient, project, agent_client) -> None:  # type: ignore[no-untyped-def]
    created = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/agents", json={"name": "Agent CSRF", "kind": "product"}
    )
    assert created.status_code == 201, created.text
    key = created.json()["api_key"]
    agent = agent_client(key)
    response = await agent.post(f"/api/v1/_test/projects/{project['slug']}/editor")
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {"Referer": "https://evil.example/page"}, {"Origin": "null"}],
)
async def test_foreign_origin_is_rejected_even_for_login(
    raw_client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await raw_client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"
    assert "orbit_session" not in response.cookies


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://testserver"])
async def test_public_and_own_origins_are_accepted(raw_client: httpx.AsyncClient, origin: str) -> None:
    response = await raw_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Origin": origin},
    )
    assert response.status_code == 200, response.text
    token = raw_client.cookies.get("orbit_csrf")
    ok = await raw_client.post(
        "/api/v1/projects", json=_project(), headers={"Origin": origin, "X-CSRF-Token": token or ""}
    )
    assert ok.status_code == 201


async def test_expired_cookie_does_not_require_a_token(raw_client: httpx.AsyncClient) -> None:
    raw_client.cookies.set("orbit_session", "not-a-valid-jwt")
    response = await raw_client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
