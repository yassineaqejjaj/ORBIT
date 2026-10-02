"""F2 — change feed: emission at write time, rights filtering, since-snapshot, digest, subscriptions."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from tests.conftest import UserInfo
from tests.test_api_documents import drain

JSON = dict[str, Any]


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}"


async def _create(client: httpx.AsyncClient, project: JSON, **overrides: Any) -> JSON:
    body: JSON = {
        "scope": "project",
        "kind": "decision",
        "title": f"Décision {uuid.uuid4().hex[:6]}",
        "content": f"Décision : le badge visiteur {uuid.uuid4().hex[:8]} est imprimé sur place.",
        "status": "validated",
    }
    body.update(overrides)
    response = await client.post(f"{_base(project)}/memory", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _changes(client: httpx.AsyncClient, project: JSON, **params: Any) -> list[JSON]:
    response = await client.get(f"{_base(project)}/changes", params={"page_size": 100, **params})
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def _member(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
    role: str,
    clearance: int = 1,
) -> tuple[UserInfo, httpx.AsyncClient]:
    user = await make_user(clearance=clearance)
    added = await admin_client.post(f"{_base(project)}/members", json={"email": user.email, "role": role})
    assert added.status_code == 201, added.text
    return user, await client_for(user)


async def test_memory_changes_are_emitted_and_filtered_by_rights(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    decision = await _create(admin_client, project, title="Badge sur place")
    fact = await _create(admin_client, project, kind="fact", title="Simple fait", status="proposed")
    secret = await _create(admin_client, project, title="Décision secrète", classification=3)
    restricted = await _create(admin_client, project, title="Décision owners", acl_principals=["role:owner"])
    await _create(admin_client, project, scope="user", kind="preference", title="Préférence privée")

    assert (await admin_client.post(f"{base}/memory/{fact['id']}/validate", json={})).status_code == 200
    obsolete = await admin_client.post(
        f"{base}/memory/{decision['id']}/obsolete", json={"reason": "Abandonné"}
    )
    assert obsolete.status_code == 200

    events = await _changes(admin_client, project)
    by_target = {(e["type"], e["target_id"]) for e in events}
    assert ("memory.created", decision["id"]) in by_target
    assert ("memory.created", fact["id"]) not in by_target  # facts are not announced on creation
    assert ("memory.validated", fact["id"]) in by_target
    assert ("memory.obsoleted", decision["id"]) in by_target
    assert ("memory.created", secret["id"]) in by_target
    assert not any("Préférence privée" in e["title"] for e in events)  # user memory never in the feed
    created = next(e for e in events if e["target_id"] == decision["id"] and e["type"] == "memory.created")
    assert created["type_label"] and created["summary"] and created["actor_label"]

    _, editor = await _member(admin_client, project, make_user, client_for, "editor", clearance=1)
    editor_targets = {e["target_id"] for e in await _changes(editor, project)}
    assert decision["id"] in editor_targets
    assert secret["id"] not in editor_targets  # clearance
    assert restricted["id"] not in editor_targets  # ACL

    only = await _changes(admin_client, project, types="memory.validated")
    assert only and all(e["type"] == "memory.validated" for e in only)
    bad = await admin_client.get(f"{base}/changes", params={"types": "nope"})
    assert bad.status_code == 422 and bad.json()["code"] == "validation_error"
    future = await _changes(admin_client, project, since=(utcnow() + timedelta(hours=1)).isoformat())
    assert future == []

    # Forgetting scrubs the wording of earlier events of the item.
    forgot = await admin_client.post(f"{base}/memory/{secret['id']}/forget", json={"reason": "RGPD"})
    assert forgot.status_code == 200, forgot.text
    events = [e for e in await _changes(admin_client, project) if e["target_id"] == secret["id"]]
    assert {e["type"] for e in events} >= {"memory.created", "memory.forgotten"}
    assert all("secrète" not in e["title"] and "secrète" not in e["summary"] for e in events)


async def test_document_events_and_stale_detection(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    base = _base(project)
    content = b"# Plan d'acces\n\nLe parking visiteurs est au niveau -2."
    uploaded = await admin_client.post(
        f"{base}/documents/upload", files=[("files", ("plan_acces.md", content, "text/markdown"))]
    )
    assert uploaded.status_code == 201, uploaded.text
    [doc] = uploaded.json()
    await drain()
    v2 = b"# Plan d'acces\n\nLe parking visiteurs est au niveau -3 depuis mars."
    await admin_client.post(
        f"{base}/documents/upload", files=[("files", ("plan_acces.md", v2, "text/markdown"))]
    )
    await drain()
    types = {e["type"] for e in await _changes(admin_client, project) if e["target_id"] == doc["id"]}
    assert {"document.ingested", "document.new_version"} <= types

    from app.features.feed.service import detect_stale_documents
    from app.models import Document

    await db_session.execute(
        update(Document)
        .where(Document.id == uuid.UUID(doc["id"]))
        .values(source_updated_at=utcnow() - timedelta(days=4000))
    )
    await db_session.commit()
    assert await detect_stale_documents(db_session) >= 1
    await db_session.commit()
    assert await detect_stale_documents(db_session) == 0  # once per document version
    stale = await _changes(admin_client, project, types="document.stale")
    assert [e["target_id"] for e in stale] == [doc["id"]]
    assert stale[0]["data"]["limit_days"] == 365


async def test_since_snapshot_lists_changes_and_outdated_items(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    from app.enums import ActorType
    from app.models import ContextSnapshot

    base = _base(project)
    kept = await _create(admin_client, project, title="Accueil 8h")
    replaced = await _create(admin_client, project, title="Navette 20 min")
    snapshot = ContextSnapshot(
        project_id=uuid.UUID(project["id"]),
        name="brief-salon",
        version=1,
        task="Brief",
        content="…",
        items=[
            {"candidate_type": "memory", "memory_item_id": kept["id"], "title": kept["title"]},
            {"candidate_type": "memory", "memory_item_id": replaced["id"], "title": replaced["title"]},
        ],
        content_hash="x",
        created_by_type=ActorType.user,
        created_at=utcnow() - timedelta(minutes=5),
    )
    db_session.add(snapshot)
    await db_session.commit()

    fresh = await admin_client.get(f"{base}/changes/since-snapshot", params={"name": "brief-salon"})
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["is_up_to_date"] is True

    newer = await _create(admin_client, project, title="Navette 15 min")
    superseded = await admin_client.post(
        f"{base}/memory/{replaced['id']}/supersede", json={"by_id": newer["id"]}
    )
    assert superseded.status_code == 200, superseded.text
    body = (
        await admin_client.get(f"{base}/changes/since-snapshot", params={"name": "brief-salon", "version": 1})
    ).json()
    assert body["is_up_to_date"] is False
    assert body["snapshot"]["name"] == "brief-salon"
    [outdated] = body["outdated"]
    assert outdated["id"] == replaced["id"] and outdated["reason"] == "superseded"
    assert outdated["replaced_by_id"] == newer["id"]
    assert {"memory.superseded", "memory.created"} <= {e["type"] for e in body["changes"]}

    missing = await admin_client.get(f"{base}/changes/since-snapshot", params={"name": "inconnu"})
    assert missing.status_code == 404


async def test_digest_and_subscriptions(
    admin_client: httpx.AsyncClient,
    project: JSON,
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base(project)
    await _create(admin_client, project, title="Vestiaire gratuit")
    default = await admin_client.get(f"{base}/subscriptions/me")
    assert default.status_code == 200 and default.json()["digest"] == "off"

    digest = await admin_client.get(f"{base}/changes/digest", params={"period": "week"})
    assert digest.status_code == 200, digest.text
    body = digest.json()
    assert body["total"] >= 1 and body["email_enabled"] is False
    assert any(g["type"] == "memory.created" for g in body["groups"])
    assert "Vestiaire gratuit" in body["text"]

    user, viewer = await _member(admin_client, project, make_user, client_for, "viewer")
    invalid = await viewer.put(f"{base}/subscriptions/me", json={"digest": "hourly", "types": []})
    assert invalid.status_code == 422
    saved = await viewer.put(
        f"{base}/subscriptions/me", json={"digest": "daily", "types": ["memory.validated"]}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["digest"] == "daily" and saved.json()["types"] == ["memory.validated"]
    assert (await viewer.get(f"{base}/subscriptions/me")).json()["digest"] == "daily"
    filtered = (await viewer.get(f"{base}/changes/digest")).json()
    assert all(g["type"] == "memory.validated" for g in filtered["groups"])

    # Worker digests: sent through SMTP only when configured.
    from app.config import settings
    from app.features.feed import service
    from app.models.features_feed import Subscription

    assert await service.send_due_digests(db_session) == 0
    sent: list[tuple[str, str, str]] = []

    async def _fake_send(to: str, subject: str, text: str) -> None:
        sent.append((to, subject, text))

    monkeypatch.setattr(settings, "smtp_host", "smtp.exemple.test")
    monkeypatch.setattr(settings, "smtp_from", "orbit@exemple.test")
    monkeypatch.setattr(service, "send_mail", _fake_send)
    await viewer.put(f"{base}/subscriptions/me", json={"digest": "daily", "types": []})
    count = await service.send_due_digests(db_session)
    await db_session.commit()
    assert count >= 1 and any(to == user.email for to, _, _ in sent)
    row = await db_session.scalar(
        select(Subscription).where(
            Subscription.user_id == user.id, Subscription.project_id == uuid.UUID(project["id"])
        )
    )
    assert row is not None and row.last_digest_at is not None
    sent.clear()
    await service.send_due_digests(db_session)
    assert not any(to == user.email for to, _, _ in sent)  # not due again before a day
