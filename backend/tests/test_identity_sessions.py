"""Server-side sessions (sid, idle/absolute expiry, revocation), account endpoints, forced password change."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update

from app.db import get_sessionmaker, utcnow
from app.identity import sessions as session_service
from app.identity.passwords import password_problems
from app.models import User
from app.models.identity import UserSession
from app.security import create_access_token, decode_access_token
from tests.conftest import UserInfo, login, unique

NEW_PASSWORD = "Orbite-Nouvelle-Cle-2026"
STRONG_PASSWORD = "Galaxie-Lointaine-4827"


async def _session_row(session_id: uuid.UUID) -> UserSession:
    async with get_sessionmaker()() as db:
        row = await db.get(UserSession, session_id)
        assert row is not None
        return row


def _sid(client: httpx.AsyncClient) -> uuid.UUID:
    token = client.cookies.get("orbit_session")
    assert token
    sid = decode_access_token(token).session_id
    assert sid is not None
    return sid


async def _set_session(session_id: uuid.UUID, **values: Any) -> None:
    async with get_sessionmaker()() as db:
        await db.execute(update(UserSession).where(UserSession.id == session_id).values(**values))
        await db.commit()


async def _set_user(user_id: uuid.UUID, **values: Any) -> None:
    async with get_sessionmaker()() as db:
        await db.execute(update(User).where(User.id == user_id).values(**values))
        await db.commit()


ClientFor = Callable[[UserInfo], Awaitable[httpx.AsyncClient]]


async def test_login_creates_server_side_session(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": user.password},
        headers={"User-Agent": "pytest-agent/1.0"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_active"] is True
    assert body["must_change_password"] is False
    assert body["auth_provider"] == "local"
    row = await _session_row(_sid(client))
    assert row.user_id == user.id
    assert row.revoked_at is None
    assert row.user_agent == "pytest-agent/1.0"
    assert row.auth_method == "password"
    assert row.ip == "127.0.0.1"
    assert timedelta(hours=11) < row.expires_at - row.created_at <= timedelta(hours=12, seconds=5)
    assert client.cookies.get("orbit_csrf")


async def test_token_without_sid_is_rejected(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    async with get_sessionmaker()() as db:
        stored = await db.get(User, user.id)
        assert stored is not None
        token = create_access_token(user.id, password_hash=stored.password_hash)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "Session invalide" in response.json()["detail"]


async def test_logout_revokes_the_session_server_side(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    await login(client, user.email, user.password)
    token = client.cookies.get("orbit_session")
    sid = _sid(client)
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    # The JWT is still cryptographically valid, but the server-side session is gone.
    replay = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert replay.status_code == 401
    assert "révoquée" in replay.json()["detail"]
    row = await _session_row(sid)
    assert row.revoked_reason == "logout"


async def test_idle_timeout_revokes_the_session(client_for: ClientFor, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    c = await client_for(user)
    sid = _sid(c)
    await _set_session(sid, last_seen_at=utcnow() - timedelta(minutes=31))
    response = await c.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "inactivité" in response.json()["detail"]
    assert (await _session_row(sid)).revoked_reason == "idle_timeout"


async def test_absolute_expiry(client_for: ClientFor, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    c = await client_for(user)
    await _set_session(_sid(c), expires_at=utcnow() - timedelta(seconds=1))
    response = await c.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "expirée" in response.json()["detail"]


async def test_activity_slides_the_idle_deadline(client_for: ClientFor, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    c = await client_for(user)
    sid = _sid(c)
    old = utcnow() - timedelta(minutes=20)
    await _set_session(sid, last_seen_at=old)
    assert (await c.get("/api/v1/auth/me")).status_code == 200
    assert (await _session_row(sid)).last_seen_at > old + timedelta(minutes=19)


async def test_deactivated_user_is_rejected(
    client_for: ClientFor, client: httpx.AsyncClient, make_user
) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    c = await client_for(user)
    await _set_user(user.id, is_active=False)
    response = await c.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "account_disabled"
    denied = await client.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
    assert denied.status_code == 403
    assert denied.json()["code"] == "account_disabled"


async def test_list_and_revoke_own_sessions(client_for: ClientFor, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    first = await client_for(user)
    second = await client_for(user)
    listed = await first.get("/api/v1/account/sessions")
    assert listed.status_code == 200
    sessions = listed.json()
    assert len(sessions) == 2
    current = [s for s in sessions if s["current"]]
    assert len(current) == 1 and current[0]["id"] == str(_sid(first))
    assert {"id", "created_at", "last_seen_at", "ip", "user_agent", "current"} <= set(sessions[0])

    other = str(_sid(second))
    assert (await first.delete(f"/api/v1/account/sessions/{other}")).status_code == 204
    assert (await second.get("/api/v1/auth/me")).status_code == 401
    assert (await first.get("/api/v1/auth/me")).status_code == 200
    # Already revoked, unknown, or someone else's session: 404.
    assert (await first.delete(f"/api/v1/account/sessions/{other}")).status_code == 404
    assert (await first.delete(f"/api/v1/account/sessions/{uuid.uuid4()}")).status_code == 404


async def test_cannot_revoke_someone_elses_session(client_for: ClientFor, make_user) -> None:  # type: ignore[no-untyped-def]
    alice, bob = await make_user(), await make_user()
    alice_client, bob_client = await client_for(alice), await client_for(bob)
    response = await alice_client.delete(f"/api/v1/account/sessions/{_sid(bob_client)}")
    assert response.status_code == 404
    assert (await bob_client.get("/api/v1/auth/me")).status_code == 200


async def test_account_password_change(client_for: ClientFor, client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    current = await client_for(user)
    other = await client_for(user)

    wrong = await current.post(
        "/api/v1/account/password", json={"current_password": "pas-le-bon", "new_password": NEW_PASSWORD}
    )
    assert wrong.status_code == 403 and wrong.json()["code"] == "invalid_password"
    weak = await current.post(
        "/api/v1/account/password", json={"current_password": user.password, "new_password": "azerty"}
    )
    assert weak.status_code == 422 and weak.json()["code"] == "weak_password"
    assert "au moins 12 caractères" in weak.json()["detail"]
    same = await current.post(
        "/api/v1/account/password", json={"current_password": user.password, "new_password": user.password}
    )
    assert same.status_code == 422 and same.json()["code"] in {"password_reused", "weak_password"}

    ok = await current.post(
        "/api/v1/account/password", json={"current_password": user.password, "new_password": NEW_PASSWORD}
    )
    assert ok.status_code == 204, ok.text
    # The current session survives (its JWT is re-minted), every other session is revoked.
    assert (await current.get("/api/v1/auth/me")).status_code == 200
    assert (await other.get("/api/v1/auth/me")).status_code == 401
    refused = await client.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
    assert refused.status_code == 401
    await login(client, user.email, NEW_PASSWORD)


async def test_admin_created_user_must_change_password(
    admin_client: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    email = f"{unique('nouveau')}@example.com"
    created = await admin_client.post(
        "/api/v1/users",
        json={"email": email, "full_name": "Nina Martin", "password": STRONG_PASSWORD, "clearance": 1},
    )
    assert created.status_code == 201, created.text
    assert created.json()["must_change_password"] is True

    first = await client.post("/api/v1/auth/login", json={"email": email, "password": STRONG_PASSWORD})
    assert first.status_code == 200
    challenge = first.json()
    assert challenge["password_change_required"] is True
    assert "orbit_session" not in first.cookies
    token = challenge["change_token"]

    weak = await client.post(
        "/api/v1/auth/password/change-required",
        json={"change_token": token, "new_password": "nina-martin-26"},
    )
    assert weak.status_code == 422 and weak.json()["code"] == "weak_password"
    reused = await client.post(
        "/api/v1/auth/password/change-required", json={"change_token": token, "new_password": STRONG_PASSWORD}
    )
    assert reused.status_code == 422 and reused.json()["code"] == "password_reused"
    changed = await client.post(
        "/api/v1/auth/password/change-required", json={"change_token": token, "new_password": NEW_PASSWORD}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["must_change_password"] is False
    assert (await client.get("/api/v1/auth/me")).json()["email"] == email
    # Single use: the password fingerprint changed.
    again = await client.post(
        "/api/v1/auth/password/change-required",
        json={"change_token": token, "new_password": STRONG_PASSWORD + "x"},
    )
    assert again.status_code == 401 and again.json()["code"] == "invalid_token"


async def test_change_token_is_not_a_session(client: httpx.AsyncClient) -> None:
    bogus = await client.post(
        "/api/v1/auth/password/change-required",
        json={"change_token": "abc.def.ghi", "new_password": NEW_PASSWORD},
    )
    assert bogus.status_code == 401 and bogus.json()["code"] == "invalid_token"


async def test_admin_password_reset_forces_change(
    admin_client: httpx.AsyncClient, client: httpx.AsyncClient, make_user, client_for: ClientFor
) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    user_client = await client_for(user)
    weak = await admin_client.patch(f"/api/v1/users/{user.id}", json={"password": "motdepasse"})
    assert weak.status_code == 422
    response = await admin_client.patch(f"/api/v1/users/{user.id}", json={"password": STRONG_PASSWORD})
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    assert (await user_client.get("/api/v1/auth/me")).status_code == 401
    challenge = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": STRONG_PASSWORD}
    )
    assert challenge.json()["password_change_required"] is True
    async with get_sessionmaker()() as db:
        live = await db.scalars(
            select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        )
        assert list(live) == []


# --- Bootstrap administrator ------------------------------------------------------------------------------


class _EmptyDb:
    """Minimal stand-in for an AsyncSession on an empty ``users`` table."""

    def __init__(self) -> None:
        self.added: list[User] = []

    async def scalar(self, _statement: object) -> int:
        return 0

    def add(self, obj: User) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


async def test_bootstrap_admin_random_one_time_password(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.config import settings
    from app.security import verify_password
    from app.services.users import ensure_bootstrap_admin

    monkeypatch.setattr(settings, "bootstrap_admin_password", "")
    db = _EmptyDb()
    with caplog.at_level(logging.WARNING, logger="orbit.users"):
        user = await ensure_bootstrap_admin(db)  # type: ignore[arg-type]
    assert user is not None and user.is_admin and user.clearance == 3
    assert user.must_change_password is True
    messages = [r.getMessage() for r in caplog.records if "One-time password" in r.getMessage()]
    assert len(messages) == 1
    password = messages[0].rsplit(": ", 1)[1]
    assert len(password) >= 24 and password_problems(password) == []
    assert verify_password(password, user.password_hash)


async def test_bootstrap_admin_configured_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.services.users import ensure_bootstrap_admin

    monkeypatch.setattr(settings, "bootstrap_admin_password", "Un-Mot-De-Passe-Fourni-2026")
    user = await ensure_bootstrap_admin(_EmptyDb())  # type: ignore[arg-type]
    assert user is not None and user.must_change_password is False


async def test_session_service_revoke_all_except_current(make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user()
    async with get_sessionmaker()() as db:
        stored = await db.get(User, user.id)
        assert stored is not None
        issued = [
            await session_service.create_session(
                db, stored, conn=None, method=session_service.AuthMethod.password
            )
            for _ in range(3)
        ]
        await db.commit()
        keep = issued[0].row.id
        count = await session_service.revoke_user_sessions(
            db, user.id, session_service.RevokeReason.admin, keep=keep
        )
        await db.commit()
        assert count == 2
        live = await session_service.list_active_sessions(db, user.id)
        assert [row.id for row in live] == [keep]
