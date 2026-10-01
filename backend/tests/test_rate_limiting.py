"""Sliding-window rate limits (login, agent keys, per-principal API) and progressive account lockout.

Each test uses its own client IP (``X-Forwarded-For`` from the trusted local proxy) and fresh accounts,
so the shared test Valkey database never leaks counters between tests.
"""

from __future__ import annotations

import random
import uuid

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import settings
from app.identity import ratelimit
from tests.conftest import login


def _ip() -> str:
    return f"198.51.{random.randint(0, 255)}.{random.randint(1, 254)}"


def _headers(ip: str) -> dict[str, str]:
    return {"X-Forwarded-For": ip}


def test_parse_limits_and_scaling() -> None:
    limits = ratelimit.parse_limits("5/minute,20/hour, 10/30s ,100/2h")
    assert [(item.count, item.window_seconds) for item in limits] == [
        (5, 60),
        (20, 3600),
        (10, 30),
        (100, 7200),
    ]
    assert ratelimit.parse_limits("") == []
    assert ratelimit.scaled("5/minute,20/hour", 10) == "50/60s,200/3600s"
    with pytest.raises(ValueError, match="invalide"):
        ratelimit.parse_limits("5/fortnight")
    with pytest.raises(ValueError, match="invalide"):
        ratelimit.parse_limits("beaucoup")


def test_rate_limited_error_is_french_with_retry_after() -> None:
    error = ratelimit.RateLimited(125.2, "Patientez {delay}.")
    assert error.status_code == 429
    assert error.headers == {"Retry-After": "126"}
    assert error.detail == "Patientez 3 minutes."
    assert ratelimit.RateLimited(1).detail == "Trop de requêtes : réessayez dans 1 seconde."


async def test_sliding_window_counts_only_recorded_hits() -> None:
    identity = uuid.uuid4().hex
    assert await ratelimit.check("unit", identity, "2/minute") == 0
    assert await ratelimit.hit("unit", identity, "2/minute") == 0
    assert await ratelimit.hit("unit", identity, "2/minute") == 0
    wait = await ratelimit.hit("unit", identity, "2/minute")
    assert 0 < wait <= 60
    assert await ratelimit.check("unit", identity, "2/minute") > 0


async def test_valkey_outage_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Down:
        async def eval(self, *_args: object) -> int:
            raise RedisConnectionError("down")

    monkeypatch.setattr(ratelimit, "_client", lambda: _Down())
    assert await ratelimit.hit("unit", "x", "1/minute") == 0
    await ratelimit.enforce("unit", "x", "1/minute")


async def test_login_is_rate_limited_per_ip_and_account(
    client: httpx.AsyncClient, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "rate_limit_login", "3/minute")
    monkeypatch.setattr(settings, "login_lockout_threshold", 100)
    user = await make_user()
    ip = _ip()
    for _ in range(3):
        response = await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "mauvais"}, headers=_headers(ip)
        )
        assert response.status_code == 401
    limited = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": user.password}, headers=_headers(ip)
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert "Trop de tentatives de connexion" in limited.json()["detail"]
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    # Another client IP is not affected.
    other = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": user.password}, headers=_headers(_ip())
    )
    assert other.status_code == 200


async def test_progressive_account_lockout(
    client: httpx.AsyncClient, make_user, monkeypatch: pytest.MonkeyPatch, db_session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "login_lockout_threshold", 2)
    monkeypatch.setattr(settings, "login_lockout_base_seconds", 60)
    user = await make_user()
    first = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "mauvais"}, headers=_headers(_ip())
    )
    assert first.status_code == 401
    locked = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "mauvais"}, headers=_headers(_ip())
    )
    assert locked.status_code == 429
    assert locked.json()["code"] == "account_locked"
    assert 55 <= int(locked.headers["Retry-After"]) <= 60
    # Even the right password is refused while locked, from any IP.
    still = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": user.password}, headers=_headers(_ip())
    )
    assert still.status_code == 429 and still.json()["code"] == "account_locked"
    from sqlalchemy import select

    from app.models import AuditLog

    actions = set(await db_session.scalars(select(AuditLog.action).where(AuditLog.target_id == str(user.id))))
    assert {"auth.login_failed", "auth.login_locked"} <= actions
    await ratelimit.reset_account(user.email)
    await login(client, user.email, user.password)


async def test_lock_duration_doubles_and_is_capped() -> None:
    account = f"{uuid.uuid4().hex}@example.com"
    durations = [
        await ratelimit.register_failure(account, threshold=1, base_seconds=60, max_seconds=200)
        for _ in range(4)
    ]
    assert durations == [60, 120, 200, 200]
    assert 190 < await ratelimit.lockout_remaining(account) <= 200
    await ratelimit.reset_account(account)
    assert await ratelimit.lockout_remaining(account) == 0


async def test_failed_agent_key_attempts_are_limited_per_ip(
    agent_client, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "rate_limit_login", "1/minute")  # x4 for agent-key failures
    ip = _ip()
    bad = agent_client("orb_abcdefgh_" + "A" * 32)
    for _ in range(4):
        response = await bad.get("/api/v1/_test/projects/inconnu/viewer", headers=_headers(ip))
        assert response.status_code == 401
    limited = await bad.get("/api/v1/_test/projects/inconnu/viewer", headers=_headers(ip))
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers


async def test_agent_calls_are_limited_per_agent(
    admin_client: httpx.AsyncClient, project, agent_client, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    created = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/agents", json={"name": "Agent pressé", "kind": "product"}
    )
    agent = agent_client(created.json()["api_key"])
    monkeypatch.setattr(settings, "rate_limit_agent", "2/minute")
    url = f"/api/v1/_test/projects/{project['slug']}/viewer"
    assert (await agent.get(url)).status_code == 200
    assert (await agent.get(url)).status_code == 200
    limited = await agent.get(url)
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"


async def test_user_api_calls_are_limited_per_user(
    client_for, make_user, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    c = await client_for(user)
    monkeypatch.setattr(settings, "rate_limit_api", "3/minute")
    for _ in range(3):
        assert (await c.get("/api/v1/auth/me")).status_code == 200
    limited = await c.get("/api/v1/auth/me")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert "Trop de requêtes" in limited.json()["detail"]
