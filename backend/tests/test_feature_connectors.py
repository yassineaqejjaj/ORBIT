"""F5 — connectors API and synchronisation: secrets, roles, anti-SSRF, credential test, wizard flow,
Jira/SharePoint sync to documents, incremental cursor, deletion → forget, change event, scheduling.

Remote services are simulated with ``httpx.MockTransport`` (no network).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from app.config import settings
from app.connectors import base as connector_base
from app.connectors import service
from app.connectors.sharepoint import GRAPH
from app.db import get_sessionmaker, utcnow
from app.enums import DocumentStatus, JobKind, JobStatus
from app.features.feed import security
from app.ingestion.queue import claim_next_job
from app.models import Document, IngestionJob, Source
from app.models.connector import Connector, ConnectorRun
from app.models.features_feed import ChangeEvent
from app.worker import Worker
from tests.conftest import UserInfo

JSON = dict[str, Any]
JIRA = "https://jira.exemple.test"
SECRET = "jira-api-token-ABCD1234"


class FakeRemote:
    """Fake Jira Cloud + Microsoft Graph."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.issues: dict[str, JSON] = {}
        self.jira_token = SECRET
        self.drive_items: list[JSON] = []
        self.delta_items: list[JSON] = []

    def issue(self, key: str, summary: str, updated: str) -> None:
        self.issues[key] = {
            "key": key,
            "fields": {
                "summary": summary,
                "description": f"Description de {key}",
                "status": {"name": "Ouvert"},
                "issuetype": {"name": "Tâche"},
                "updated": updated,
                "comment": {
                    "comments": [{"author": {"displayName": "Ana"}, "created": updated, "body": "Vu."}],
                    "total": 1,
                },
            },
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(JIRA):
            return self._jira(request)
        if "login.microsoftonline.com" in url:
            return httpx.Response(200, json={"access_token": "graph-token"})
        if url.startswith("https://download.exemple.test/"):
            return httpx.Response(200, content=b"# Note SharePoint\n\nLe quai B ferme a 18 h.")
        if url.startswith(f"{GRAPH}/drives/d1/root/delta"):
            if "token=1" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": self.delta_items,
                        "@odata.deltaLink": f"{GRAPH}/drives/d1/root/delta?token=2",
                    },
                )
            return httpx.Response(
                200,
                json={"value": self.drive_items, "@odata.deltaLink": f"{GRAPH}/drives/d1/root/delta?token=1"},
            )
        return httpx.Response(404)

    def _jira(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != connector_base_auth(self.jira_token):
            return httpx.Response(401, json={"errorMessages": ["Jeton invalide"]})
        path = request.url.path
        if path == "/rest/api/2/myself":
            return httpx.Response(200, json={"displayName": "Robot ORBIT"})
        if path == "/rest/api/2/project/search":
            return httpx.Response(200, json={"values": [{"key": "ORB", "name": "Orbit"}]})
        if path == "/rest/api/2/search/jql":
            return httpx.Response(200, json={"issues": list(self.issues.values()), "isLast": True})
        if path.startswith("/rest/api/2/issue/"):
            key = path.rsplit("/", 1)[-1]
            if key in self.issues:
                return httpx.Response(200, json={"key": key})
            return httpx.Response(404)
        return httpx.Response(404)


def connector_base_auth(token: str) -> str:
    from app.connectors.confluence import basic_auth

    return basic_auth("bot@exemple.test", token)


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRemote]:
    fake = FakeRemote()
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())

    async def _resolve(host: str, port: int) -> list[str]:
        return {"interne.exemple.test": ["10.0.0.8"]}.get(host, ["93.184.216.34"])

    async def _sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(security, "resolve_host", _resolve)
    monkeypatch.setattr(connector_base, "transport_override", httpx.MockTransport(fake))
    monkeypatch.setattr(connector_base, "sleep", _sleep)
    yield fake


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/connectors"


def _jira_body(**overrides: Any) -> JSON:
    body: JSON = {
        "type": "jira",
        "name": "Jira Orbit",
        "config": {"base_url": JIRA, "email": "bot@exemple.test", "jql": "project = ORB"},
        "secret": SECRET,
    }
    body.update(overrides)
    return body


async def _run_connector_jobs() -> int:
    worker = Worker(concurrency=1, worker_id="test-connectors")
    processed = 0
    for _ in range(20):
        async with get_sessionmaker()() as session:
            job = await claim_next_job(session, worker.worker_id, kinds=(JobKind.connector_sync,))
        if job is None:
            break
        await worker._process(job.id)
        processed += 1
    return processed


async def test_connector_requires_encryption_key(admin_client: httpx.AsyncClient, project: JSON) -> None:
    response = await admin_client.post(_base(project), json=_jira_body())
    assert response.status_code == 503
    assert response.json()["code"] == "encryption_key_missing"
    assert "connecteurs" in response.json()["detail"]


async def test_crud_secret_masking_roles_and_ssrf(
    admin_client: httpx.AsyncClient,
    project: JSON,
    remote: FakeRemote,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    types = (await admin_client.get(f"{base}/types")).json()
    assert {t["type"] for t in types} == {"sharepoint", "confluence", "jira"}

    created = await admin_client.post(
        base, json=_jira_body(restrict_to_editors=True, default_classification=2)
    )
    assert created.status_code == 201, created.text
    connector = created.json()
    assert SECRET not in created.text and connector["secret_hint"] == "••••1234" and connector["has_secret"]
    assert connector["acl_principals"] == ["role:editor"] and connector["default_classification"] == 2
    assert connector["schedule_minutes"] == settings.connector_default_schedule_minutes
    assert connector["status"] == "idle" and connector["suggested_task"]
    async with get_sessionmaker()() as session:
        row = await session.get(Connector, connector["id"])
        assert row is not None and row.secret_ciphertext and SECRET not in row.secret_ciphertext
        source = await session.get(Source, row.source_id)
        assert source is not None and source.kind == "ticket" and source.default_acl == ["role:editor"]

    listing = await admin_client.get(base)
    assert SECRET not in listing.text and [c["id"] for c in listing.json()] == [connector["id"]]

    for config, fragment in (
        ({"base_url": "http://jira.exemple.test"}, "HTTPS"),
        ({"base_url": "https://interne.exemple.test"}, "anti-SSRF"),
        ({"base_url": "https://127.0.0.1"}, "anti-SSRF"),
    ):
        body = _jira_body(config={"email": "bot@exemple.test", "jql": "project = ORB", **config})
        refused = await admin_client.post(base, json=body)
        assert refused.status_code == 422, refused.text
        assert fragment in refused.json()["detail"]
    missing_scope = await admin_client.post(
        base, json=_jira_body(config={"base_url": JIRA, "email": "a@b.fr"})
    )
    assert missing_scope.status_code == 422 and "JQL" in missing_scope.json()["detail"]

    patched = await admin_client.patch(
        f"{base}/{connector['id']}",
        json={"secret": "nouveau-secret-9876", "paused": True, "name": "Jira ORB"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["secret_hint"] == "••••9876" and patched.json()["paused"] is True
    assert "nouveau-secret" not in patched.text

    viewer_user, editor_user = await make_user(), await make_user()
    for user, role in ((viewer_user, "viewer"), (editor_user, "editor")):
        added = await admin_client.post(
            f"/api/v1/projects/{project['slug']}/members", json={"email": user.email, "role": role}
        )
        assert added.status_code == 201, added.text
    viewer, editor = await client_for(viewer_user), await client_for(editor_user)
    assert (await viewer.get(base)).status_code == 200
    assert (await viewer.post(f"{base}/{connector['id']}/sync")).status_code == 403
    assert (await editor.post(base, json=_jira_body())).status_code == 403
    assert (await editor.post(f"{base}/test", json=_jira_body())).status_code == 403
    assert (await editor.delete(f"{base}/{connector['id']}")).status_code == 403

    deleted = await admin_client.delete(f"{base}/{connector['id']}")
    assert deleted.status_code == 204
    assert (await admin_client.get(f"{base}/{connector['id']}")).status_code == 404
    audit = await admin_client.get(
        f"/api/v1/projects/{project['slug']}/audit", params={"action": "connector"}
    )
    actions = {e["action"] for e in audit.json()["items"]}
    assert actions >= {"connector.create", "connector.update", "connector.delete"}
    assert SECRET not in audit.text and "nouveau-secret" not in audit.text


async def test_credential_test_endpoint_does_not_ingest(
    admin_client: httpx.AsyncClient, project: JSON, remote: FakeRemote
) -> None:
    base = _base(project)
    body = {k: v for k, v in _jira_body().items() if k in ("type", "config", "secret")}
    ok = await admin_client.post(f"{base}/test", json=body)
    assert ok.status_code == 200, ok.text
    result = ok.json()
    assert result["ok"] is True and result["account"] == "Robot ORBIT" and "JQL valide" in result["message"]
    assert result["scope_options"] == [
        {"id": "ORB", "label": "Orbit (ORB)", "kind": "project", "parent_id": None, "description": ""}
    ]
    bad = await admin_client.post(f"{base}/test", json={**body, "secret": "mauvais"})
    assert bad.status_code == 200 and bad.json()["ok"] is False
    assert "Identifiants refusés" in bad.json()["message"]
    assert (await admin_client.get(base)).json() == []  # nothing stored

    created = (await admin_client.post(base, json=_jira_body())).json()
    retest = await admin_client.post(f"{base}/{created['id']}/test")
    assert retest.status_code == 200 and retest.json()["ok"] is True
    retest_bad = await admin_client.post(f"{base}/{created['id']}/test", json={"secret": "autre"})
    assert retest_bad.json()["ok"] is False
    async with get_sessionmaker()() as session:
        count = len(
            list(await session.scalars(select(Document.id).where(Document.project_id == project["id"])))
        )
    assert count == 0


async def test_wizard_flow_jira_sync_incremental_and_forget(
    admin_client: httpx.AsyncClient, project: JSON, remote: FakeRemote
) -> None:
    base = _base(project)
    remote.issue("ORB-1", "Fermeture du quai B", "2026-09-29T10:00:00.000+0000")
    remote.issue("ORB-2", "Capacité entrepôt", "2026-09-30T10:00:00.000+0000")
    created = await admin_client.post(base, json=_jira_body(start_sync=True, restrict_to_editors=True))
    assert created.status_code == 201, created.text
    connector = created.json()
    assert connector["status"] == "syncing" and connector["last_run"]["status"] == "queued"
    assert connector["last_run"]["trigger"] == "initial"
    again = await admin_client.post(f"{base}/{connector['id']}/sync")
    assert again.status_code == 409

    assert await _run_connector_jobs() == 1
    run = (await admin_client.get(f"{base}/{connector['id']}/runs/{connector['last_run']['id']}")).json()
    assert run["status"] == "succeeded", run
    assert (run["fetched"], run["created"], run["updated"], run["forgotten"], run["errors"]) == (
        2,
        2,
        0,
        0,
        0,
    )
    assert run["duration_ms"] is not None and run["progress"]["phase"] == "done"
    detail = (await admin_client.get(f"{base}/{connector['id']}")).json()
    assert detail["status"] == "ok" and detail["document_count"] == 2 and detail["last_sync_at"]

    async with get_sessionmaker()() as session:
        docs = {
            d.external_id: d
            for d in await session.scalars(select(Document).where(Document.source_id == detail["source_id"]))
        }
        assert set(docs) == {"ORB-1", "ORB-2"}
        assert (
            docs["ORB-1"].acl_principals == ["role:editor"]
            and docs["ORB-1"].title == "ORB-1 — Fermeture du quai B"
        )
        row = await session.get(Connector, connector["id"])
        assert row is not None and row.cursor["updated"].startswith("2026-09-30T10:00")
        events = list(
            await session.scalars(
                select(ChangeEvent).where(
                    ChangeEvent.project_id == project["id"], ChangeEvent.type == "connector.synced"
                )
            )
        )
        assert len(events) == 1 and events[0].data["created"] == 2

    # Second sync: ORB-1 changed, ORB-2 deleted at the source.
    remote.issue("ORB-1", "Fermeture du quai B (reportée)", "2026-10-01T10:00:00.000+0000")
    del remote.issues["ORB-2"]
    remote.requests.clear()
    manual = await admin_client.post(f"{base}/{connector['id']}/sync")
    assert manual.status_code == 202 and manual.json()["trigger"] == "manual"
    await _run_connector_jobs()
    run = (await admin_client.get(f"{base}/{connector['id']}/runs/{manual.json()['id']}")).json()
    assert (run["status"], run["updated"], run["forgotten"]) == ("succeeded", 1, 1), run
    jqls = [r.url.params.get("jql", "") for r in remote.requests if r.url.path.endswith("/search/jql")]
    assert any('updated >= "2026/09/29 10:00"' in jql for jql in jqls), jqls
    async with get_sessionmaker()() as session:
        forgotten = await session.scalar(
            select(Document).where(Document.source_id == detail["source_id"], Document.external_id == "ORB-2")
        )
        assert forgotten is not None and forgotten.status == DocumentStatus.forgotten
        forget_jobs = await session.scalars(
            select(IngestionJob).where(
                IngestionJob.document_id == forgotten.id, IngestionJob.kind == JobKind.forget
            )
        )
        assert len(list(forget_jobs)) == 1

    runs = (await admin_client.get(f"{base}/{connector['id']}/runs")).json()
    assert runs["total"] == 2 and runs["items"][0]["id"] == manual.json()["id"]

    # Auth failure: the run fails with a French message, the connector shows the error.
    remote.jira_token = "rotated"
    failing = await admin_client.post(f"{base}/{connector['id']}/sync")
    await _run_connector_jobs()
    run = (await admin_client.get(f"{base}/{connector['id']}/runs/{failing.json()['id']}")).json()
    assert run["status"] == "failed" and "Identifiants refusés" in run["error"]
    detail = (await admin_client.get(f"{base}/{connector['id']}")).json()
    assert detail["status"] == "error" and "Identifiants refusés" in detail["last_error"]


async def test_sharepoint_sync_delta_deletion(
    admin_client: httpx.AsyncClient, project: JSON, remote: FakeRemote
) -> None:
    remote.drive_items = [
        {
            "id": "n1",
            "name": "note-quai.md",
            "size": 40,
            "file": {"mimeType": "text/markdown"},
            "@microsoft.graph.downloadUrl": "https://download.exemple.test/n1",
        },
        {"id": "x1", "name": "setup.exe", "size": 40, "file": {}},
    ]
    remote.delta_items = [{"id": "n1", "deleted": {"state": "deleted"}}]
    body = {
        "type": "sharepoint",
        "name": "Intranet",
        "config": {
            "tenant_id": "tenant",
            "client_id": "client",
            "drive_ids": ["d1"],
            "scope_labels": ["Intranet"],
        },
        "secret": "graph-client-secret-XYZ",
        "default_classification": 2,
        "start_sync": True,
    }
    created = await admin_client.post(_base(project), json=body)
    assert created.status_code == 201, created.text
    connector = created.json()
    assert "Intranet" in connector["suggested_task"]
    await _run_connector_jobs()
    run = (await admin_client.get(f"{_base(project)}/{connector['id']}/runs")).json()["items"][0]
    assert (run["created"], run["skipped"]) == (1, 1), run
    async with get_sessionmaker()() as session:
        doc = await session.scalar(select(Document).where(Document.external_id == "d1:n1"))
        assert doc is not None and doc.classification == 2 and doc.acl_principals == ["project:*"]
        source = await session.get(Source, doc.source_id)
        assert source is not None and source.kind == "document"
    await admin_client.post(f"{_base(project)}/{connector['id']}/sync")
    await _run_connector_jobs()
    run = (await admin_client.get(f"{_base(project)}/{connector['id']}/runs")).json()["items"][0]
    assert run["forgotten"] == 1, run
    async with get_sessionmaker()() as session:
        doc = await session.scalar(select(Document).where(Document.external_id == "d1:n1"))
        assert doc is not None and doc.status == DocumentStatus.forgotten


async def test_scheduling_of_due_syncs(
    admin_client: httpx.AsyncClient, project: JSON, remote: FakeRemote
) -> None:
    base = _base(project)
    due = (await admin_client.post(base, json=_jira_body(name="Dû", schedule_minutes=60))).json()
    recent = (await admin_client.post(base, json=_jira_body(name="Récent", schedule_minutes=60))).json()
    manual_only = (await admin_client.post(base, json=_jira_body(name="Manuel", schedule_minutes=0))).json()
    paused = (await admin_client.post(base, json=_jira_body(name="En pause"))).json()
    await admin_client.patch(f"{base}/{paused['id']}", json={"paused": True})
    async with get_sessionmaker()() as session:
        await session.execute(
            update(Connector)
            .where(Connector.id == due["id"])
            .values(last_sync_at=utcnow() - timedelta(hours=2))
        )
        await session.execute(
            update(Connector)
            .where(Connector.id == recent["id"])
            .values(last_sync_at=utcnow() - timedelta(minutes=5))
        )
        await session.commit()
    async with get_sessionmaker()() as session:
        await service.run_connector_maintenance(session)
        await session.commit()
    async with get_sessionmaker()() as session:
        runs = list(
            await session.scalars(select(ConnectorRun).where(ConnectorRun.project_id == project["id"]))
        )
        assert [(str(r.connector_id), r.trigger) for r in runs] == [(due["id"], "schedule")]
        assert runs[0].job_id is not None
        job = await session.get(IngestionJob, runs[0].job_id)
        assert job is not None and job.kind == JobKind.connector_sync and job.status == JobStatus.queued
    # A run is already queued: no duplicate.
    async with get_sessionmaker()() as session:
        await service.run_connector_maintenance(session)
        await session.commit()
        count = len(
            list(await session.scalars(select(ConnectorRun.id).where(ConnectorRun.connector_id == due["id"])))
        )
        assert count == 1
    assert manual_only["schedule_minutes"] == 0
