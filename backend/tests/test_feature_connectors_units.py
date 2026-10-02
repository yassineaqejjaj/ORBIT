"""F5 — connector clients without database: mapping, pagination, incremental cursor, deletions, retries.

Every remote call goes through ``httpx.MockTransport`` (no network).
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from app.connectors import base
from app.connectors.base import Change, ConnectorError, HttpClient, retry_after_seconds
from app.connectors.confluence import ConfluenceConnector
from app.connectors.jira import JiraConnector, adf_text
from app.connectors.sharepoint import GRAPH, SharePointConnector

Handler = Callable[[httpx.Request], httpx.Response]


class Recorder:
    def __init__(self) -> None:
        self.handler: Handler = lambda request: httpx.Response(404)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    recorder = Recorder()
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(base, "transport_override", httpx.MockTransport(recorder))
    monkeypatch.setattr(base, "sleep", _sleep)
    recorder.sleeps = sleeps  # type: ignore[attr-defined]
    yield recorder


async def _collect(connector: Any, cursor: dict[str, Any] | None = None) -> list[Change]:
    try:
        return [change async for change in connector.changes(cursor or {})]
    finally:
        await connector.aclose()


# --- HTTP client: retries ------------------------------------------------------------------------------


def test_retry_after_parsing() -> None:
    assert retry_after_seconds("7") == 7
    assert retry_after_seconds("100000") == base.MAX_RETRY_AFTER_SECONDS
    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0  # past date
    assert retry_after_seconds("n'importe quoi") is None
    assert retry_after_seconds(None) is None


async def test_retry_after_is_honoured_then_success(remote: Recorder) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    remote.handler = handler
    async with HttpClient() as client:
        assert await client.get_json("https://api.exemple.test/x") == {"ok": True}
        assert client.retries == 2
    assert remote.sleeps == [7.0, 7.0]  # type: ignore[attr-defined]


async def test_backoff_without_retry_after_and_exhaustion(remote: Recorder) -> None:
    remote.handler = lambda request: httpx.Response(503)
    async with HttpClient(max_retries=2) as client:
        with pytest.raises(ConnectorError) as info:
            await client.get_json("https://api.exemple.test/x")
    assert info.value.status_code == 503
    assert len(remote.requests) == 3
    sleeps = remote.sleeps  # type: ignore[attr-defined]
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] > 0


async def test_auth_error_is_flagged(remote: Recorder) -> None:
    remote.handler = lambda request: httpx.Response(401, json={"message": "Bad token"})
    async with HttpClient() as client:
        with pytest.raises(ConnectorError) as info:
            await client.get_json("https://api.exemple.test/x")
    assert (
        info.value.auth and "Identifiants refusés" in info.value.message and "Bad token" in info.value.message
    )


# --- SharePoint --------------------------------------------------------------------------------------


def _sharepoint_handler(pages: dict[str, dict[str, Any]], *, token_status: int = 200) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "login.microsoftonline.com" in url:
            body = request.content.decode()
            assert "grant_type=client_credentials" in body and "client_secret=s3cr3t" in body
            if token_status != 200:
                return httpx.Response(token_status, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if url.startswith("https://download.exemple.test/"):
            assert "authorization" not in request.headers
            return httpx.Response(200, content=b"%PDF-1.4 contenu")
        assert request.headers["authorization"] == "Bearer tok"
        for prefix, payload in pages.items():
            if url.startswith(prefix):
                if payload.get("_status"):
                    return httpx.Response(payload["_status"])
                return httpx.Response(200, json=payload)
        return httpx.Response(404)

    return handler


def _sp(**config: Any) -> SharePointConnector:
    return SharePointConnector(
        {"tenant_id": "t", "client_id": "c", "site_ids": [], "drive_ids": ["d1"], **config}, "s3cr3t"
    )


async def test_sharepoint_delta_mapping_pagination_and_cursor(remote: Recorder) -> None:
    file_item = {
        "id": "i1",
        "name": "Plan de capacité.pdf",
        "size": 10,
        "file": {"mimeType": "application/pdf"},
        "webUrl": "https://acme.sharepoint.com/sites/x/Plan.pdf",
        "lastModifiedDateTime": "2026-09-30T08:00:00Z",
        "lastModifiedBy": {"user": {"displayName": "Camille Martin"}},
        "parentReference": {"path": "/drive/root:/Projets"},
        "@microsoft.graph.downloadUrl": "https://download.exemple.test/i1",
    }
    remote.handler = _sharepoint_handler(
        {
            f"{GRAPH}/drives/d1/root/delta?token=page2": {
                "value": [
                    {"id": "i2", "deleted": {"state": "deleted"}},
                    {
                        "id": "i3",
                        "name": "outil.exe",
                        "size": 5,
                        "file": {"mimeType": "application/x-msdownload"},
                    },
                    {"id": "i4", "name": "énorme.pdf", "size": 10**12, "file": {}},
                ],
                "@odata.deltaLink": f"{GRAPH}/drives/d1/root/delta?token=next",
            },
            f"{GRAPH}/drives/d1/root/delta": {
                "value": [{"id": "root", "folder": {}}, file_item],
                "@odata.nextLink": f"{GRAPH}/drives/d1/root/delta?token=page2",
            },
        }
    )
    connector = _sp()
    changes = await _collect(connector)
    assert [c.external_id for c in changes] == ["d1:i1", "d1:i2", "d1:i3", "d1:i4"]
    first = changes[0]
    assert first.data == b"%PDF-1.4 contenu" and first.mime_type == "application/pdf"
    assert first.author == "Camille Martin" and first.uri and first.updated_at is not None
    assert changes[1].deleted
    assert changes[2].skip_reason and "Format" in changes[2].skip_reason
    assert changes[3].skip_reason and "volumineux" in changes[3].skip_reason
    assert connector.next_cursor == {"delta": {"d1": f"{GRAPH}/drives/d1/root/delta?token=next"}}

    # Incremental: the stored delta link is used as is.
    remote.requests.clear()
    remote.handler = _sharepoint_handler(
        {f"{GRAPH}/drives/d1/root/delta?token=next": {"value": [], "@odata.deltaLink": f"{GRAPH}/x?token=n2"}}
    )
    connector = _sp()
    assert await _collect(connector, {"delta": {"d1": f"{GRAPH}/drives/d1/root/delta?token=next"}}) == []
    assert any("token=next" in str(r.url) for r in remote.requests)
    assert connector.next_cursor["delta"]["d1"].endswith("token=n2")


async def test_sharepoint_expired_delta_restarts_and_foreign_links_refused(remote: Recorder) -> None:
    remote.handler = _sharepoint_handler(
        {
            f"{GRAPH}/drives/d1/root/delta?token=old": {"_status": 410},
            f"{GRAPH}/drives/d1/root/delta": {"value": [], "@odata.deltaLink": f"{GRAPH}/fresh"},
        }
    )
    connector = _sp()
    await _collect(connector, {"delta": {"d1": f"{GRAPH}/drives/d1/root/delta?token=old"}})
    assert connector.next_cursor == {"delta": {"d1": f"{GRAPH}/fresh"}}

    remote.handler = _sharepoint_handler(
        {f"{GRAPH}/drives/d1/root/delta": {"value": [], "@odata.nextLink": "https://evil.exemple.test/steal"}}
    )
    with pytest.raises(ConnectorError, match="hôte refusé"):
        await _collect(_sp())


async def test_sharepoint_test_lists_sites_and_drives(remote: Recorder) -> None:
    remote.handler = _sharepoint_handler(
        {
            f"{GRAPH}/sites?": {
                "value": [{"id": "s1", "displayName": "Équipe Projet", "webUrl": "https://x"}]
            },
            f"{GRAPH}/sites/s1/drives": {"value": [{"id": "d1", "name": "Documents partagés"}]},
        }
    )
    connector = _sp(drive_ids=[])
    result = await connector.test()
    await connector.aclose()
    assert result.ok and "1 site" in result.message
    assert [(o.kind, o.id, o.parent_id) for o in result.scope_options] == [
        ("site", "s1", None),
        ("drive", "d1", "s1"),
    ]

    remote.handler = _sharepoint_handler({}, token_status=400)
    connector = _sp()
    with pytest.raises(ConnectorError) as info:
        await connector.test()
    await connector.aclose()
    assert info.value.auth and "Microsoft Entra" in info.value.message


def test_sharepoint_config_validation() -> None:
    with pytest.raises(ValueError, match="tenant"):
        SharePointConnector.validate_config({"client_id": "c"}, require_scope=False)
    with pytest.raises(ValueError, match="au moins un site"):
        SharePointConnector.validate_config({"tenant_id": "t", "client_id": "c"}, require_scope=True)
    clean = SharePointConnector.validate_config(
        {"tenant_id": "t", "client_id": "c", "site_ids": "s1, s2", "client_secret": "fuite"},
        require_scope=True,
    )
    assert clean["site_ids"] == ["s1", "s2"] and "client_secret" not in clean


# --- Confluence -------------------------------------------------------------------------------------


CONF = "https://acme.atlassian.net/wiki"


def _page(page_id: str, title: str, when: str) -> dict[str, Any]:
    return {
        "id": page_id,
        "type": "page",
        "status": "current",
        "title": title,
        "space": {"key": "ORB"},
        "version": {"number": 3, "when": when, "by": {"displayName": "Lina Dupont"}},
        "body": {"storage": {"value": "<p>Le quai <strong>B</strong> ferme à 18 h.</p>"}},
        "_links": {"webui": f"/spaces/ORB/pages/{page_id}"},
    }


def _confluence() -> ConfluenceConnector:
    config = ConfluenceConnector.validate_config(
        {"base_url": "https://acme.atlassian.net", "email": "bot@acme.test", "space_keys": ["orb"]},
        require_scope=True,
    )
    return ConfluenceConnector(config, "api-token")


async def test_confluence_mapping_pagination_and_cursor(remote: Recorder) -> None:
    seen_cql: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        expected = "Basic " + base64.b64encode(b"bot@acme.test:api-token").decode()
        assert request.headers["authorization"] == expected
        assert request.url.path == "/wiki/rest/api/content/search"
        if request.url.params.get("cursor") == "c2":
            return httpx.Response(
                200, json={"results": [_page("102", "Procédure", "2026-09-29T10:00:00.000Z")]}
            )
        seen_cql.append(request.url.params["cql"])
        return httpx.Response(
            200,
            json={
                "results": [_page("101", "Accueil", "2026-09-28T10:00:00.000Z")],
                "_links": {"next": "/wiki/rest/api/content/search?cursor=c2&limit=50"},
            },
        )

    remote.handler = handler
    connector = _confluence()
    assert connector.root == CONF
    changes = await _collect(connector)
    assert [c.external_id for c in changes] == ["101", "102"]
    page = changes[0]
    assert page.mime_type == "text/html" and page.data and b"Le quai <strong>B</strong>" in page.data
    assert page.uri == f"{CONF}/spaces/ORB/pages/101" and page.author == "Lina Dupont"
    assert page.metadata["space"] == "ORB"
    assert 'space IN ("ORB")' in seen_cql[0] and "lastmodified >" not in seen_cql[0]
    assert connector.next_cursor["last_modified"].startswith("2026-09-29T10:00")

    # Incremental: CQL lastmodified with a safety overlap.
    seen_cql.clear()
    connector = _confluence()
    await _collect(connector, {"last_modified": "2026-09-29T10:00:00+00:00"})
    assert 'lastmodified > "2026/09/28 10:00"' in seen_cql[0] and seen_cql[0].endswith(
        "ORDER BY lastmodified ASC"
    )


async def test_confluence_confirm_deleted(remote: Recorder) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/content/search"):
            return httpx.Response(200, json={"results": [{"id": "1"}]})
        if path.endswith("/content/2"):
            return httpx.Response(404)
        if path.endswith("/content/3"):
            return httpx.Response(200, json={"id": "3", "status": "trashed"})
        if path.endswith("/content/4"):  # moved to a space outside the scope: kept
            return httpx.Response(200, json={"id": "4", "status": "current"})
        return httpx.Response(500)

    remote.handler = handler
    connector = _confluence()
    assert await connector.confirm_deleted({"1", "2", "3", "4"}) == ["2", "3"]
    await connector.aclose()


async def test_confluence_test_with_pat(remote: Recorder) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer pat-123"
        if request.url.path.endswith("/user/current"):
            return httpx.Response(200, json={"displayName": "Robot ORBIT"})
        return httpx.Response(
            200, json={"results": [{"key": "ORB", "name": "Orbit"}, {"key": "OPS", "name": "Ops"}]}
        )

    remote.handler = handler
    config = ConfluenceConnector.validate_config(
        {"base_url": "https://confluence.acme.test/", "deployment": "datacenter"}, require_scope=False
    )
    assert config["base_url"] == "https://confluence.acme.test" and config["email"] == ""
    connector = ConfluenceConnector(config, "pat-123")
    result = await connector.test()
    await connector.aclose()
    assert (
        result.ok
        and result.account == "Robot ORBIT"
        and [o.id for o in result.scope_options] == ["ORB", "OPS"]
    )


# --- Jira -----------------------------------------------------------------------------------------


JIRA = "https://acme.atlassian.net"


def _issue(key: str, updated: str, *, comments: int = 1, total: int | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "fields": {
            "summary": f"Résumé {key}",
            "description": "Le transporteur doit livrer avant 9 h.",
            "status": {"name": "En cours"},
            "issuetype": {"name": "Tâche"},
            "priority": {"name": "Haute"},
            "assignee": {"displayName": "Noé Petit"},
            "reporter": {"displayName": "Ana Leroy"},
            "labels": ["quai", "transport"],
            "project": {"key": key.split("-")[0], "name": "Orbit"},
            "created": "2026-09-01T09:00:00.000+0200",
            "updated": updated,
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Ana Leroy"},
                        "created": "2026-09-02T10:00:00.000+0200",
                        "body": f"Commentaire {i}",
                    }
                    for i in range(comments)
                ],
                "total": total if total is not None else comments,
            },
        },
    }


def _jira(**config: Any) -> JiraConnector:
    clean = JiraConnector.validate_config(
        {"base_url": JIRA, "email": "bot@acme.test", "jql": "project = ORB", **config}, require_scope=True
    )
    return JiraConnector(clean, "tok")


async def test_jira_cloud_pagination_comments_and_cursor(remote: Recorder) -> None:
    seen_jql: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/2/search/jql":
            seen_jql.append(request.url.params["jql"])
            if request.url.params.get("nextPageToken") == "p2":
                return httpx.Response(
                    200, json={"issues": [_issue("ORB-2", "2026-09-30T11:00:00.000+0200")], "isLast": True}
                )
            return httpx.Response(
                200,
                json={
                    "issues": [_issue("ORB-1", "2026-09-29T11:00:00.000+0200", comments=1, total=2)],
                    "nextPageToken": "p2",
                },
            )
        if path == "/rest/api/2/issue/ORB-1/comment":
            assert request.url.params["startAt"] == "1"
            return httpx.Response(
                200,
                json={
                    "comments": [{"author": {"displayName": "Noé Petit"}, "body": "Validé avec le client."}]
                },
            )
        return httpx.Response(404)

    remote.handler = handler
    connector = _jira()
    changes = await _collect(connector)
    assert [c.external_id for c in changes] == ["ORB-1", "ORB-2"]
    first = changes[0]
    assert first.title == "ORB-1 — Résumé ORB-1" and first.uri == f"{JIRA}/browse/ORB-1"
    assert first.text and "## Commentaires (2)" in first.text and "Validé avec le client." in first.text
    assert "- **Statut** : En cours" in first.text and "Le transporteur doit livrer" in first.text
    assert seen_jql[0] == "(project = ORB) ORDER BY updated ASC"
    assert connector.next_cursor["updated"].startswith("2026-09-30T11:00:00+02:00")

    seen_jql.clear()
    connector = _jira()
    await _collect(connector, {"updated": "2026-09-30T09:00:00+00:00"})
    assert seen_jql[0] == '(project = ORB) AND updated >= "2026/09/29 09:00" ORDER BY updated ASC'


async def test_jira_datacenter_start_at_pagination_and_pat(remote: Recorder) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        assert request.url.path == "/rest/api/2/search"
        start = int(request.url.params["startAt"])
        issues = [_issue(f"OPS-{start + 1}", "2026-09-29T11:00:00.000+0000", comments=0)]
        return httpx.Response(200, json={"issues": issues, "total": 3, "startAt": start})

    remote.handler = handler
    connector = _jira(
        base_url="https://jira.acme.test", deployment="datacenter", email="", jql="project = OPS"
    )
    changes = await _collect(connector)
    assert [c.external_id for c in changes] == ["OPS-1", "OPS-2", "OPS-3"]
    assert "## Commentaires" not in (changes[0].text or "")


async def test_jira_confirm_deleted_and_invalid_jql(remote: Recorder) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/2/search/jql":
            if "nimporte" in request.url.params["jql"]:
                return httpx.Response(400, json={"errorMessages": ["Erreur dans la requête JQL"]})
            return httpx.Response(200, json={"issues": [{"key": "ORB-1"}], "isLast": True})
        if path == "/rest/api/2/issue/ORB-2":
            return httpx.Response(404)
        if path == "/rest/api/2/issue/ORB-3":
            return httpx.Response(200, json={"key": "NEW-7"})  # moved
        if path == "/rest/api/2/issue/ORB-4":
            return httpx.Response(200, json={"key": "ORB-4"})  # outside the JQL now: kept
        if path == "/rest/api/2/myself":
            return httpx.Response(200, json={"displayName": "Robot"})
        if path == "/rest/api/2/project/search":
            return httpx.Response(200, json={"values": [{"key": "ORB", "name": "Orbit"}]})
        return httpx.Response(500)

    remote.handler = handler
    connector = _jira()
    assert await connector.confirm_deleted({"ORB-1", "ORB-2", "ORB-3", "ORB-4"}) == ["ORB-2", "ORB-3"]
    result = await connector.test()
    assert result.ok and "JQL valide" in result.message and result.scope_options[0].id == "ORB"
    await connector.aclose()
    connector = _jira(jql="nimporte quoi")
    result = await connector.test()
    await connector.aclose()
    assert not result.ok and "JQL" in result.message


def test_jira_validation_and_adf() -> None:
    with pytest.raises(ValueError, match="ORDER BY"):
        JiraConnector.validate_config(
            {"base_url": JIRA, "email": "a@b.c", "jql": "x = 1 order by created"}, require_scope=True
        )
    with pytest.raises(ValueError, match="E-mail"):
        JiraConnector.validate_config({"base_url": JIRA, "jql": "x = 1"}, require_scope=True)
    with pytest.raises(ValueError, match="https"):
        JiraConnector.validate_config({"base_url": "ftp://x", "email": "a@b.c"}, require_scope=False)
    doc = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Bonjour"}]}],
    }
    assert adf_text(doc).strip() == "Bonjour"
