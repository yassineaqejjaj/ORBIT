"""F2 — webhooks: owner CRUD, secret shown once, anti-SSRF, signed delivery, redaction, retries, auto-disable."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from app.config import settings
from app.db import get_sessionmaker, utcnow
from app.enums import JobKind, JobStatus
from app.features.feed import delivery, security
from app.ingestion.queue import claim_next_job
from app.models import IngestionJob
from app.models.features_feed import Webhook, WebhookDelivery
from app.worker import Worker
from tests.conftest import UserInfo

JSON = dict[str, Any]
PUBLIC_IP = "93.184.216.34"


class Receiver:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"ok": self.status < 300})


@pytest.fixture
def receiver(monkeypatch: pytest.MonkeyPatch) -> Iterator[Receiver]:
    target = Receiver()
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())

    async def _resolve(host: str, port: int) -> list[str]:
        return {"interne.exemple.test": ["192.168.1.20"]}.get(host, [PUBLIC_IP])

    monkeypatch.setattr(security, "resolve_host", _resolve)
    monkeypatch.setattr(delivery, "transport_override", httpx.MockTransport(target))
    yield target


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/webhooks"


async def _hook(client: httpx.AsyncClient, project: JSON, **body: Any) -> JSON:
    response = await client.post(_base(project), json={"url": "https://hooks.exemple.test/orbit", **body})
    assert response.status_code == 201, response.text
    return response.json()


async def _decision(client: httpx.AsyncClient, project: JSON, **overrides: Any) -> JSON:
    body: JSON = {
        "scope": "project",
        "kind": "decision",
        "title": f"Décision {uuid.uuid4().hex[:6]}",
        "content": f"Décision : le vestiaire {uuid.uuid4().hex[:8]} est gratuit.",
        "status": "validated",
    }
    body.update(overrides)
    response = await client.post(f"/api/v1/projects/{project['slug']}/memory", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _run_webhook_jobs(*, force: bool = True) -> int:
    worker = Worker(concurrency=1, worker_id="test-webhooks")
    processed = 0
    for _ in range(50):
        async with get_sessionmaker()() as session:
            if force:  # ignore the retry backoff
                await session.execute(
                    update(IngestionJob)
                    .where(IngestionJob.kind == JobKind.webhook, IngestionJob.status == JobStatus.queued)
                    .values(run_after=utcnow())
                )
                await session.commit()
            job = await claim_next_job(session, worker.worker_id, kinds=(JobKind.webhook,))
        if job is None:
            break
        await worker._process(job.id)
        processed += 1
    return processed


async def test_webhook_requires_encryption_key(admin_client: httpx.AsyncClient, project: JSON) -> None:
    response = await admin_client.post(_base(project), json={"url": "https://hooks.exemple.test/x"})
    assert response.status_code == 503
    assert response.json()["code"] == "encryption_key_missing"
    assert "ORBIT_ENCRYPTION_KEY" in response.json()["detail"]


async def test_webhook_crud_secret_once_and_ssrf(
    admin_client: httpx.AsyncClient,
    project: JSON,
    receiver: Receiver,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    created = await _hook(admin_client, project, types=["memory.validated"], description="CRM")
    assert created["secret"].startswith("whsec_") and created["enabled"] is True
    assert created["secret_hint"] and created["secret"] not in created["secret_hint"]
    listing = (await admin_client.get(base)).json()
    assert [h["id"] for h in listing] == [created["id"]]
    assert "secret" not in listing[0]

    for url, fragment in (
        ("http://hooks.exemple.test/x", "HTTPS"),
        ("https://127.0.0.1/x", "anti-SSRF"),
        ("https://10.1.2.3/x", "anti-SSRF"),
        ("https://[::1]/x", "anti-SSRF"),
        ("https://169.254.169.254/latest", "anti-SSRF"),
        ("https://interne.exemple.test/x", "anti-SSRF"),
        ("https://user:pass@hooks.exemple.test/x", "identifiants"),
    ):
        refused = await admin_client.post(base, json={"url": url})
        assert refused.status_code == 422, url
        assert fragment in refused.json()["detail"], refused.json()
    bad_type = await admin_client.post(base, json={"url": "https://hooks.exemple.test/x", "types": ["nope"]})
    assert bad_type.status_code == 422

    patched = await admin_client.patch(
        f"{base}/{created['id']}", json={"enabled": False, "description": "CRM v2"}
    )
    assert patched.status_code == 200 and patched.json()["enabled"] is False
    assert patched.json()["description"] == "CRM v2"
    ssrf_patch = await admin_client.patch(f"{base}/{created['id']}", json={"url": "https://127.0.0.1/x"})
    assert ssrf_patch.status_code == 422

    user = await make_user()
    await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": user.email, "role": "editor"}
    )
    editor = await client_for(user)
    assert (await editor.get(base)).status_code == 403
    assert (await editor.post(base, json={"url": "https://hooks.exemple.test/x"})).status_code == 403

    deleted = await admin_client.delete(f"{base}/{created['id']}")
    assert deleted.status_code == 204
    assert (await admin_client.get(base)).json() == []
    assert (await admin_client.delete(f"{base}/{created['id']}")).status_code == 404
    audit = await admin_client.get(f"/api/v1/projects/{project['slug']}/audit", params={"action": "webhook"})
    assert {e["action"] for e in audit.json()["items"]} >= {
        "webhook.create",
        "webhook.update",
        "webhook.delete",
    }


async def test_signed_delivery_and_redaction(
    admin_client: httpx.AsyncClient, project: JSON, receiver: Receiver
) -> None:
    hook = await _hook(admin_client, project, types=["memory.created"])
    public = await _decision(admin_client, project, title="Vestiaire gratuit")
    confidential = await _decision(admin_client, project, title="Budget confidentiel", classification=2)
    await _decision(admin_client, project, kind="fact", title="Fait non annoncé")
    assert await _run_webhook_jobs() == 2

    by_target: dict[str, tuple[httpx.Request, JSON]] = {}
    for request in receiver.requests:
        body = json.loads(request.content)
        by_target[body["target_id"]] = (request, body)
        expected = "sha256=" + hmac.new(hook["secret"].encode(), request.content, hashlib.sha256).hexdigest()
        assert request.headers["X-Orbit-Signature"] == expected
        assert request.headers["X-Orbit-Event"] == "memory.created"
        assert uuid.UUID(request.headers["X-Orbit-Delivery"])
    _, public_body = by_target[public["id"]]
    assert public_body["restricted"] is False and "Vestiaire gratuit" in public_body["title"]
    assert public_body["project"]["slug"] == project["slug"]
    _, secret_body = by_target[confidential["id"]]
    assert secret_body["restricted"] is True
    assert secret_body["title"] == "Élément restreint" and secret_body["summary"] == ""
    assert "confidentiel" not in json.dumps(secret_body).lower()

    deliveries = await admin_client.get(f"{_base(project)}/{hook['id']}/deliveries")
    assert deliveries.status_code == 200
    items = deliveries.json()["items"]
    assert len(items) == 2 and {d["status"] for d in items} == {"succeeded"}
    assert all(d["response_status"] == 200 and d["attempts"] == 1 for d in items)

    tested = await admin_client.post(f"{_base(project)}/{hook['id']}/test")
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "succeeded" and tested.json()["event_type"] == "ping"
    assert receiver.requests[-1].headers["X-Orbit-Event"] == "ping"


async def test_retries_then_auto_disable(
    admin_client: httpx.AsyncClient, project: JSON, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "webhook_max_failures", 3)
    hook = await _hook(admin_client, project)
    receiver.status = 500
    await _decision(admin_client, project)

    # First attempt fails: the delivery stays pending and the job is re-queued with a backoff.
    assert await _run_webhook_jobs(force=False) == 1
    async with get_sessionmaker()() as session:
        row = await session.scalar(
            select(WebhookDelivery).where(WebhookDelivery.webhook_id == uuid.UUID(hook["id"]))
        )
        assert row is not None and row.status == "pending" and row.attempts == 1
        assert row.error == "Réponse HTTP 500"
        job = await session.scalar(
            select(IngestionJob).where(IngestionJob.payload["delivery_id"].astext == str(row.id))
        )
        assert job is not None and job.status == JobStatus.queued and job.run_after > utcnow()
        stored = await session.get(Webhook, uuid.UUID(hook["id"]))
        assert stored is not None and stored.consecutive_failures == 1 and stored.enabled

    # Further failures reach the threshold: the webhook is disabled and the delivery abandoned.
    await _run_webhook_jobs()
    state = next(h for h in (await admin_client.get(_base(project))).json() if h["id"] == hook["id"])
    assert state["enabled"] is False and state["consecutive_failures"] == 3
    assert "Désactivé automatiquement" in state["disabled_reason"]
    deliveries = (await admin_client.get(f"{_base(project)}/{hook['id']}/deliveries")).json()["items"]
    assert deliveries[0]["status"] == "failed" and deliveries[0]["attempts"] == 3
    audit = await admin_client.get(
        f"/api/v1/projects/{project['slug']}/audit", params={"action": "webhook.disabled"}
    )
    assert audit.json()["items"]

    # Disabled: new events are not delivered; re-enabling resets the counter.
    await _decision(admin_client, project)
    assert await _run_webhook_jobs() == 0
    enabled = await admin_client.patch(f"{_base(project)}/{hook['id']}", json={"enabled": True})
    assert enabled.json()["enabled"] is True and enabled.json()["consecutive_failures"] == 0
    receiver.status = 200
    await _decision(admin_client, project)
    assert await _run_webhook_jobs() == 1
    assert (await admin_client.get(f"{_base(project)}/{hook['id']}/deliveries")).json()["items"][0][
        "status"
    ] == "succeeded"


async def test_ssrf_rechecked_at_delivery(
    admin_client: httpx.AsyncClient, project: JSON, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = await _hook(admin_client, project)

    async def _rebound(host: str, port: int) -> list[str]:
        return ["10.0.0.7"]  # DNS now points to a private address

    monkeypatch.setattr(security, "resolve_host", _rebound)
    await _decision(admin_client, project)
    assert await _run_webhook_jobs() == 1
    [row] = (await admin_client.get(f"{_base(project)}/{hook['id']}/deliveries")).json()["items"]
    assert row["status"] == "failed" and "anti-SSRF" in row["error"]
    assert receiver.requests == []


def test_signature_and_ip_helpers() -> None:
    assert security.sign("s", b"{}") == "sha256=" + hmac.new(b"s", b"{}", hashlib.sha256).hexdigest()
    assert security.is_forbidden_ip("127.0.0.1") and security.is_forbidden_ip("::ffff:10.0.0.1")
    assert security.is_forbidden_ip("fe80::1") and security.is_forbidden_ip("172.16.0.1")
    assert not security.is_forbidden_ip(PUBLIC_IP)
