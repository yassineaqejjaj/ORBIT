"""F4 — Microsoft Teams outgoing webhook: HMAC, encrypted secret, replay protection, user mapping."""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.context import retrieval
from app.features.teams import service
from app.models.features_ask import Integration
from tests.conftest import UserInfo
from tests.test_feature_ask_support import add_member, seed_atlas

SECRET = base64.b64encode(os.urandom(32)).decode()
AAD_ID = "00000000-aaaa-bbbb-cccc-000000000001"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unavailable(*_args: Any, **_kwargs: Any) -> list[retrieval.IndexHit]:
        raise retrieval.RetrievalUnavailable("tests: index désactivé")

    monkeypatch.setattr(retrieval, "search_index", _unavailable)
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())


@pytest.fixture
async def teams(
    admin_client: httpx.AsyncClient,
    project: dict[str, Any],
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
    db_session: AsyncSession,
) -> dict[str, Any]:
    slug = str(project["slug"])
    viewer = await make_user(clearance=1, name="Vera Viewer")
    outsider = await make_user(clearance=1, name="Olga Externe")
    await add_member(admin_client, slug, viewer)
    await seed_atlas(db_session, project, viewer.id)
    response = await admin_client.put(
        f"/api/v1/projects/{slug}/integrations/teams",
        json={
            "secret": SECRET,
            "app_url": "https://orbit.example",
            "user_mapping": [{"teams_id": AAD_ID, "user_id": str(viewer.id)}],
        },
    )
    assert response.status_code == 200, response.text
    return {"slug": slug, "viewer": viewer, "outsider": outsider, "viewer_client": await client_for(viewer)}


def _activity(text: str = "<at>ORBIT</at> Pourquoi a-t-on choisi une PWA ?", **author: Any) -> bytes:
    return json.dumps(
        {
            "type": "message",
            "id": uuid.uuid4().hex,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "text": text,
            "from": author or {"id": "29:teams-user", "name": "Vera", "aadObjectId": AAD_ID},
        }
    ).encode()


async def _post(client: httpx.AsyncClient, slug: str, body: bytes, secret: str = SECRET) -> httpx.Response:
    return await client.post(
        f"/api/v1/integrations/teams/{slug}",
        content=body,
        headers={"Authorization": service.sign(body, secret), "Content-Type": "application/json"},
    )


async def test_configuration_is_encrypted_and_owner_only(
    teams: dict[str, Any], admin_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    slug = teams["slug"]
    out = (await admin_client.get(f"/api/v1/projects/{slug}/integrations/teams")).json()
    assert out["configured"] and out["enabled"] and out["encryption_available"]
    assert out["webhook_path"] == f"/api/v1/integrations/teams/{slug}"
    assert out["user_mapping"][0]["user_label"] == "Vera Viewer"
    assert SECRET not in json.dumps(out)
    integration = await db_session.scalar(select(Integration).where(Integration.kind == "teams"))
    assert integration is not None and SECRET not in integration.secret_encrypted
    assert service.decrypt_secret(integration.secret_encrypted) == SECRET

    response = await teams["viewer_client"].get(f"/api/v1/projects/{slug}/integrations/teams")
    assert response.status_code == 403


async def test_configuration_refused_without_encryption_key(
    project: dict[str, Any], admin_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "encryption_key", "")
    response = await admin_client.put(
        f"/api/v1/projects/{project['slug']}/integrations/teams", json={"secret": SECRET}
    )
    assert response.status_code == 409
    assert "ORBIT_ENCRYPTION_KEY" in response.json()["detail"]


async def test_mapping_requires_project_members(
    teams: dict[str, Any], admin_client: httpx.AsyncClient
) -> None:
    response = await admin_client.put(
        f"/api/v1/projects/{teams['slug']}/integrations/teams",
        json={"user_mapping": [{"teams_id": "olga@example.com", "user_id": str(teams["outsider"].id)}]},
    )
    assert response.status_code == 422


async def test_valid_signature_answers_in_teams_format(
    teams: dict[str, Any], client: httpx.AsyncClient
) -> None:
    response = await _post(client, teams["slug"], _activity())
    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply["type"] == "message"
    assert "PWA" in reply["text"] and "[S" in reply["text"]
    assert "**Sources**" in reply["text"]
    assert f"https://orbit.example/projects/{teams['slug']}/ask?conversation=" in reply["text"]

    conversations = (
        await teams["viewer_client"].get(f"/api/v1/projects/{teams['slug']}/ask/conversations")
    ).json()
    assert conversations and conversations[0]["channel"] == "teams"


async def test_invalid_signature_and_replay(teams: dict[str, Any], client: httpx.AsyncClient) -> None:
    body = _activity()
    other_secret = base64.b64encode(os.urandom(32)).decode()
    assert (await _post(client, teams["slug"], body, other_secret)).status_code == 401
    response = await client.post(
        f"/api/v1/integrations/teams/{teams['slug']}",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401
    tampered = await client.post(
        f"/api/v1/integrations/teams/{teams['slug']}",
        content=body.replace(b"PWA", b"XSS"),
        headers={"Authorization": service.sign(body, SECRET)},
    )
    assert tampered.status_code == 401

    assert (await _post(client, teams["slug"], body)).status_code == 200
    replay = await _post(client, teams["slug"], body)
    assert replay.status_code == 409

    stale = json.loads(_activity())
    stale["timestamp"] = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    assert (await _post(client, teams["slug"], json.dumps(stale).encode())).status_code == 401


async def test_unlinked_author_and_unknown_project(teams: dict[str, Any], client: httpx.AsyncClient) -> None:
    response = await _post(client, teams["slug"], _activity(aadObjectId="unknown", name="Inconnu"))
    assert response.status_code == 200
    assert response.json()["text"] == service.NOT_LINKED

    # E-mail of an ORBIT account that is not a member of the project: still not linked.
    response = await _post(client, teams["slug"], _activity(email=teams["outsider"].email, name="Olga"))
    assert response.json()["text"] == service.NOT_LINKED

    response = await _post(client, "projet-inexistant", _activity())
    assert response.status_code == 404


async def test_disconnect(
    teams: dict[str, Any], admin_client: httpx.AsyncClient, client: httpx.AsyncClient
) -> None:
    response = await admin_client.delete(f"/api/v1/projects/{teams['slug']}/integrations/teams")
    assert response.status_code == 204
    assert (await _post(client, teams["slug"], _activity())).status_code == 404
