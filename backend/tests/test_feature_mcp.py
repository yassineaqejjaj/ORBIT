"""F6 — MCP connectors and the MarkItDown fallback extractor.

Fake MCP servers (``tests/mcp_fake_server.py``) expose tools shaped like the real ones (names and
arguments from the discovery of the pinned versions). They run over **stdio** (real subprocess, env
isolation, timeout/kill), **in-process** or **streamable HTTP** (ASGI app, Bearer check): no network.
All contents are fictitious.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import settings
from app.connectors.mcp import client as mcp_client
from app.connectors.mcp import connector as mcp_connector
from app.connectors.mcp.client import McpCallError, McpClient, StdioTarget, redact
from app.connectors.mcp.mapper import as_datetime, csv_rows, drive_lines, find_list, payload
from app.db import get_sessionmaker
from app.enums import DocumentStatus, JobKind
from app.features.feed import security
from app.ingestion.extractors import detect_mime_type, is_supported, markitdown, needs_conversion
from app.ingestion.queue import claim_next_job
from app.models import Document, IngestionJob
from app.models.connector import Connector, ConnectorRun
from app.worker import Worker
from tests import mcp_fake_server
from tests.conftest import UserInfo

JSON = dict[str, Any]
FAKE = str(Path(__file__).with_name("mcp_fake_server.py"))
ATL_TOKEN = "atl-token-SECRET-4242"
PRESET_BY_COMMAND = {
    "mcp-atlassian": "atlassian",
    "mcp-obsidian": "obsidian",
    "slack-mcp-server": "slack",
    "ms-365-mcp-server": "ms365",
    "github-mcp-server": "github",
}
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class Fakes:
    """Data files of the fake servers and the transport chosen per preset (stdio or in-process)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.in_process: set[str] = set()

    def path(self, preset: str) -> Path:
        return self.root / f"{preset}.json"

    def write(self, preset: str, data: JSON) -> None:
        self.path(preset).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def calls(self, preset: str) -> list[JSON]:
        log = Path(f"{self.path(preset)}.calls.jsonl")
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def route(self, target: Any) -> Any:
        if not isinstance(target, StdioTarget):
            return None
        name = Path(target.command).name
        preset = PRESET_BY_COMMAND.get(name, "custom" if name == "fake-custom" else None)
        if preset is None:
            return None
        if preset in self.in_process or preset == "custom":
            return mcp_fake_server.build(preset, str(self.path(preset)))
        return StdioTarget(
            command=sys.executable, args=[FAKE, preset, str(self.path(preset))], env=target.env
        )


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Fakes]:
    fake = Fakes(tmp_path)
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())

    async def _resolve(host: str, port: int) -> list[str]:
        return {"interne.exemple.test": ["10.0.0.8"]}.get(host, ["93.184.216.34"])

    monkeypatch.setattr(security, "resolve_host", _resolve)
    monkeypatch.setattr(
        mcp_connector, "resolve_command", lambda command, fallback=None: [f"/opt/mcp/bin/{command}"]
    )
    monkeypatch.setattr(mcp_client, "target_override", fake.route)
    yield fake


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/connectors"


async def _run_connector_jobs() -> int:
    worker = Worker(concurrency=1, worker_id="test-mcp")
    processed = 0
    for _ in range(20):
        async with get_sessionmaker()() as session:
            job = await claim_next_job(session, worker.worker_id, kinds=(JobKind.connector_sync,))
        if job is None:
            break
        await worker._process(job.id)
        processed += 1
    return processed


async def _drain_ingest() -> None:
    worker = Worker(concurrency=1, worker_id="test-mcp-ingest")
    for _ in range(50):
        async with get_sessionmaker()() as session:
            job = await claim_next_job(session, worker.worker_id, kinds=(JobKind.ingest,))
        if job is None:
            return
        await worker._process(job.id)


async def _docs(source_id: str) -> dict[str, Document]:
    async with get_sessionmaker()() as session:
        rows = await session.scalars(select(Document).where(Document.source_id == source_id))
        return {str(d.external_id): d for d in rows}


async def _last_run(admin_client: httpx.AsyncClient, base: str, connector_id: str) -> JSON:
    runs = (await admin_client.get(f"{base}/{connector_id}/runs")).json()
    return runs["items"][0]


def _probe(body: JSON) -> JSON:
    """Body of ``POST /connectors/test`` (type, config, secret only)."""
    return {k: body[k] for k in ("type", "config", "secret")}


def _atlassian_body(**overrides: Any) -> JSON:
    body: JSON = {
        "type": "mcp",
        "name": "Atlassian Orbit",
        "config": {
            "preset": "atlassian",
            "confluence_url": "https://exemple.atlassian.net/wiki",
            "jira_url": "https://exemple.atlassian.net",
            "username": "robot@exemple.test",
            "space_keys": ["ORB"],
            "jql": "project = ORB ORDER BY created DESC",
        },
        "secret": json.dumps({"api_token": ATL_TOKEN}),
    }
    body.update(overrides)
    return body


def _atlassian_data() -> JSON:
    return {
        "token": ATL_TOKEN,
        "pages": [
            {
                "id": "101",
                "space": "ORB",
                "title": "Décision PWA",
                "updated": "2026-09-29T10:00:00.000Z",
                "body": "Nous avons choisi une PWA pour le mode hors ligne.",
                "url": "https://exemple.atlassian.net/wiki/101",
            },
            {
                "id": "102",
                "space": "ORB",
                "title": "Contraintes réseau",
                "updated": "2026-09-30T09:00:00.000Z",
                "body": "Le quai B n'a pas de réseau fiable.",
            },
            {
                "id": "900",
                "space": "AUTRE",
                "title": "Hors périmètre",
                "updated": "2026-09-30T09:00:00.000Z",
                "body": "Ne doit pas être synchronisé.",
            },
        ],
        "issues": [
            {
                "key": "ORB-1",
                "summary": "Fermeture du quai B",
                "description": "Le quai B ferme à 18 h.",
                "status": {"name": "Ouvert"},
                "issue_type": {"name": "Tâche"},
                "updated": "2026-09-30T10:00:00.000+0000",
                "url": "https://exemple.atlassian.net/browse/ORB-1",
                "comments": [
                    {"author": {"display_name": "Ana"}, "body": "Validé en comité.", "created": "2026-09-30"}
                ],
            },
        ],
    }


# --- unit: parsing, redaction --------------------------------------------------------------------------


def test_mapper_parsing_tolerates_shapes() -> None:
    import mcp_types as t

    text = t.CallToolResult(
        content=[t.TextContent(type="text", text='{"issues": [{"key": "A-1"}], "total": 1}')]
    )
    assert find_list(payload(text), "issues") == [{"key": "A-1"}]
    structured = t.CallToolResult(content=[], structured_content={"result": '[{"id": 1}]'})
    assert payload(structured) == [{"id": 1}]
    raw = t.CallToolResult(content=[t.TextContent(type="text", text="pas du JSON")])
    assert payload(raw) == "pas du JSON" and find_list(payload(raw)) == []
    rows = csv_rows('MsgID,UserName,Text,Cursor\n1790000000.0001,ana,"Bonjour, équipe",\n')
    assert rows[0]["text"] == "Bonjour, équipe" and rows[0]["msgid"].startswith("1790000000")
    files, token = drive_lines(
        '- Name: "ADR 001" (ID: abc123, Type: application/vnd.google-apps.document, Size: 12, '
        "Modified: 2026-09-30T10:00:00.000Z) Link: https://docs.example.test/abc\nnextPageToken: tok2"
    )
    assert (
        files[0]["id"] == "abc123" and files[0]["modifiedTime"].startswith("2026-09-30") and token == "tok2"
    )
    assert as_datetime("1790000000.000100").year == 2026 and as_datetime("2026-09-30 10:00").hour == 10
    assert as_datetime({"bad": 1}) is None


def test_redaction_of_secrets_and_tokens() -> None:
    text = "Bearer ghp_abcdefgh12345 api_key=zzzz9999 xoxb-1234-abcd lin_api_abcdef123 mon-secret-maison"
    cleaned = redact(text, ["mon-secret-maison"])
    for leak in ("ghp_abcdefgh12345", "zzzz9999", "xoxb-1234-abcd", "lin_api_abcdef123", "mon-secret-maison"):
        assert leak not in cleaned


# --- stdio: env isolation, timeout/kill, start-up failure ----------------------------------------------


async def test_stdio_env_isolation_and_temp_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORBIT_SENTINEL_SECRET", "ne-doit-pas-fuiter")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fuite-aws")
    target = StdioTarget(
        command=sys.executable, args=[FAKE, "env"], env={"JIRA_API_TOKEN": "jeton-du-connecteur"}
    )
    async with McpClient(target, timeout=30, secrets=["jeton-du-connecteur"]) as client:
        assert {t.name for t in await client.list_tools()} >= {"debug_env", "sleep_forever"}
        info = json.loads((await client.call_tool("debug_env", {})).content[0].text)
        home = info["env"]["HOME"]
    env = info["env"]
    assert env["JIRA_API_TOKEN"] == "jeton-du-connecteur"
    assert "ORBIT_SENTINEL_SECRET" not in env and "AWS_SECRET_ACCESS_KEY" not in env
    assert not any(key.startswith("ORBIT_") for key in env)
    assert home != os.path.expanduser("~") and "orbit-mcp-" in home and env["TMPDIR"] == home
    assert env["USER"] == "orbit" and info["cwd"].endswith(os.path.basename(home))
    assert not os.path.exists(home)  # temporary HOME removed on close


async def test_stdio_timeout_kills_the_server_process() -> None:
    target = StdioTarget(command=sys.executable, args=[FAKE, "env"])
    client = McpClient(target, timeout=3)
    await client.start()
    try:
        pid = json.loads((await client.call_tool("debug_env", {})).content[0].text)["pid"]
        with pytest.raises(McpCallError) as caught:
            await client.call_tool("sleep_forever", {"seconds": 60})
        assert "Délai dépassé" in caught.value.message
        with pytest.raises(McpCallError):
            await client.call_tool("debug_env", {})  # session is closed after a timeout
    finally:
        await client.aclose()
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("le processus du serveur MCP est toujours vivant")


async def test_stdio_startup_failure_reports_redacted_stderr() -> None:
    secret = "xoxp-1111-2222-tres-secret"
    target = StdioTarget(command=sys.executable, args=[FAKE, "crash"], env={"SLACK_MCP_XOXP_TOKEN": secret})
    with pytest.raises(McpCallError) as caught:
        async with McpClient(target, timeout=20, secrets=[secret], label="serveur MCP Slack"):
            pass
    assert "Authentication failed" in caught.value.message and secret not in caught.value.message
    assert caught.value.auth


# --- API: types, credentials test, end-to-end sync (stdio) ---------------------------------------------


async def test_types_list_presets_with_fields(admin_client: httpx.AsyncClient, project: JSON) -> None:
    types = (await admin_client.get(f"{_base(project)}/types")).json()
    presets = {t["preset"]: t for t in types if t["via_mcp"]}
    assert set(presets) == {
        "atlassian",
        "ms365",
        "google_workspace",
        "slack",
        "github",
        "linear",
        "obsidian",
        "figma",
    }
    atlassian = presets["atlassian"]
    assert atlassian["type"] == "mcp" and atlassian["icon"] == "atlassian" and atlassian["credentials_help"]
    groups = {f["key"]: f["group"] for f in atlassian["fields"]}
    assert (
        groups["api_token"] == "secret"
        and groups["space_keys"] == "scope"
        and groups["jira_url"] == "connection"
    )
    assert "confluence_search" in atlassian["required_tools"] and atlassian["docs_url"].startswith("https://")


async def test_atlassian_wizard_sync_incremental_and_secrets(
    admin_client: httpx.AsyncClient, project: JSON, fakes: Fakes, caplog: pytest.LogCaptureFixture
) -> None:
    base = _base(project)
    fakes.write("atlassian", _atlassian_data())

    tested = await admin_client.post(f"{base}/test", json=_probe(_atlassian_body()))
    assert tested.status_code == 200, tested.text
    result = tested.json()
    assert result["ok"] is True, result
    assert {"confluence_search", "jira_search"} <= set(result["tools"]) and result["account"].startswith(
        "fake-atlassian"
    )

    wrong_body = _probe(_atlassian_body(secret=json.dumps({"api_token": "mauvais-jeton-77"})))
    wrong = await admin_client.post(f"{base}/test", json=wrong_body)
    assert wrong.json()["ok"] is False and "401" in wrong.json()["message"]
    assert "mauvais-jeton-77" not in wrong.text

    missing = await admin_client.post(
        f"{base}/test", json=_probe(_atlassian_body(secret=json.dumps({"autre": "x"})))
    )
    assert missing.status_code == 422 and "Jeton" in missing.json()["detail"]

    created = await admin_client.post(
        base, json=_atlassian_body(start_sync=True, default_classification=2, restrict_to_editors=True)
    )
    assert created.status_code == 201, created.text
    connector = created.json()
    assert connector["via_mcp"] and connector["preset"] == "atlassian"
    assert connector["type_label"] == "Confluence & Jira (MCP)"
    assert ATL_TOKEN not in created.text and connector["secret_hint"] == "••••4242"
    async with get_sessionmaker()() as session:
        row = await session.get(Connector, connector["id"])
        assert row is not None and ATL_TOKEN not in (row.secret_ciphertext or "")
        assert "api_token" not in json.dumps(row.config)

    assert await _run_connector_jobs() >= 1
    run = await _last_run(admin_client, base, connector["id"])
    assert run["status"] == "succeeded", run
    assert (run["fetched"], run["created"], run["errors"]) == (3, 3, 0)
    docs = await _docs(connector["source_id"])
    assert set(docs) == {"confluence:101", "confluence:102", "jira:ORB-1"}
    page = docs["confluence:101"]
    assert page.classification == 2 and page.acl_principals == ["role:editor"]
    assert page.title == "Décision PWA" and page.uri == "https://exemple.atlassian.net/wiki/101"
    async with get_sessionmaker()() as session:
        row = await session.get(Connector, connector["id"])
        assert row is not None
        assert row.cursor["confluence:ORB"].startswith("2026-09-30T09:00")
        assert row.cursor["jira"].startswith("2026-09-30T10:00")

    # Second sync: one page changed; incremental CQL/JQL, dedupe of the unchanged content.
    data = _atlassian_data()
    data["pages"][0].update(updated="2026-10-01T08:00:00.000Z", body="La PWA est confirmée (v2).")
    fakes.write("atlassian", data)
    manual = await admin_client.post(f"{base}/{connector['id']}/sync")
    assert manual.status_code == 202
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, connector["id"])
    assert run["status"] == "succeeded" and run["updated"] == 1 and run["created"] == 0, run
    queries = [
        c["args"].get("query", "") for c in fakes.calls("atlassian") if c["tool"] == "confluence_search"
    ]
    assert any('lastmodified >= "2026-09-30 09:00"' in q for q in queries), queries
    jqls = [c["args"]["jql"] for c in fakes.calls("atlassian") if c["tool"] == "jira_search"]
    assert any('updated >= "2026/09/30 10:00"' in q and q.endswith("ORDER BY updated ASC") for q in jqls), (
        jqls
    )

    # The remote token is rotated: the run fails with a French, redacted message.
    data["token"] = "jeton-roule"
    fakes.write("atlassian", data)
    await admin_client.post(f"{base}/{connector['id']}/sync")
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, connector["id"])
    assert run["status"] == "failed" and "401" in run["error"] and ATL_TOKEN not in json.dumps(run)
    detail = (await admin_client.get(f"{base}/{connector['id']}")).json()
    assert detail["status"] == "error" and ATL_TOKEN not in json.dumps(detail)
    assert ATL_TOKEN not in caplog.text


async def test_obsidian_full_listing_deletion_limits_and_ssrf(
    admin_client: httpx.AsyncClient, project: JSON, fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _base(project)
    fakes.in_process.add("obsidian")
    notes = {
        "Projets/ORBIT/decision.md": "# Décision\n\nOn garde PostgreSQL.",
        "Projets/ORBIT/archives/risques.md": "# Risques\n\nPanne réseau au quai B.",
        "Journal/2026-10-01.md": "# Journal personnel (hors périmètre)",
    }
    fakes.write("obsidian", {"notes": notes})
    body = {
        "type": "mcp",
        "name": "Coffre projet",
        "config": {"preset": "obsidian", "host": "obsidian.exemple.test", "folders": ["Projets/ORBIT"]},
        "secret": json.dumps({"api_key": "obsidian-key-123456"}),
        "start_sync": True,
    }
    ssrf = await admin_client.post(
        base, json={**body, "config": {**body["config"], "host": "interne.exemple.test"}}
    )
    assert ssrf.status_code == 422 and "anti-SSRF" in ssrf.json()["detail"]

    created = await admin_client.post(base, json=body)
    assert created.status_code == 201, created.text
    connector = created.json()
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, connector["id"])
    assert (run["status"], run["created"]) == ("succeeded", 2), run
    docs = await _docs(connector["source_id"])
    assert set(docs) == {"notes:Projets/ORBIT/decision.md", "notes:Projets/ORBIT/archives/risques.md"}

    # Item limit: partial run, no deletion inferred from a truncated listing.
    monkeypatch.setattr(settings, "mcp_max_items", 1)
    del notes["Projets/ORBIT/decision.md"]
    notes["Projets/ORBIT/nouvelle.md"] = "# Nouvelle note"
    notes["Projets/ORBIT/autre.md"] = "# Autre note"
    fakes.write("obsidian", {"notes": notes})
    await admin_client.post(f"{base}/{connector['id']}/sync")
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, connector["id"])
    assert run["status"] == "partial" and run["forgotten"] == 0, run
    assert "Limite" in run["error_samples"][0]["error"]

    # Complete listing: the note deleted in the vault is forgotten in ORBIT.
    monkeypatch.setattr(settings, "mcp_max_items", 500)
    await admin_client.post(f"{base}/{connector['id']}/sync")
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, connector["id"])
    assert run["status"] == "succeeded" and run["forgotten"] == 1, run
    docs = await _docs(connector["source_id"])
    assert docs["notes:Projets/ORBIT/decision.md"].status == DocumentStatus.forgotten


async def test_slack_messages_grouped_per_day_with_threads(
    admin_client: httpx.AsyncClient, project: JSON, fakes: Fakes
) -> None:
    base = _base(project)
    fakes.write(
        "slack",
        {
            "messages": {
                "C0001": [
                    {"ts": "1790000000.000100", "user": "ana", "text": "On valide la PWA ?"},
                    {
                        "ts": "1790000100.000200",
                        "user": "bob",
                        "text": "Oui, décision prise",
                        "thread": "1790000100.000200",
                    },
                    {"ts": "1790090000.000300", "user": "ana", "text": "Le quai B ferme à 18 h"},
                ]
            },
            "replies": {
                "1790000100.000200": [
                    {"ts": "1790000200.000400", "user": "carla", "text": "Noté pour le compte rendu"}
                ]
            },
        },
    )
    body = {
        "type": "mcp",
        "name": "Slack projet",
        "config": {"preset": "slack", "channels": ["C0001"], "history_days": 400},
        "secret": json.dumps({"token": "xoxb-0000-fictif"}),
    }
    tested = (await admin_client.post(f"{base}/test", json=_probe(body))).json()
    assert tested["ok"] is True and {"C0001", "C0002"} <= {o["id"] for o in tested["scope_options"]}
    created = await admin_client.post(base, json={**body, "start_sync": True})
    assert created.status_code == 201, created.text
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, created.json()["id"])
    assert (run["status"], run["created"]) == ("succeeded", 2), run
    docs = await _docs(created.json()["source_id"])
    day = next(d for key, d in docs.items() if key.startswith("slack:C0001:"))
    assert day.title.startswith("Slack C0001 — 2026-")
    async with get_sessionmaker()() as session:
        jobs = list(await session.scalars(select(IngestionJob).where(IngestionJob.document_id == day.id)))
        assert jobs
    calls = fakes.calls("slack")
    assert any(c["tool"] == "conversations_replies" for c in calls)
    assert any(c["tool"] == "conversations_history" and c["args"]["limit"] == "400d" for c in calls)


async def test_github_over_streamable_http_with_bearer(
    admin_client: httpx.AsyncClient, project: JSON, fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx2
    from mcp.server.transport_security import TransportSecuritySettings

    base = _base(project)
    token = "ghp_FictifGithubToken1234"
    fakes.write(
        "github",
        {
            "token": f"Bearer {token}",
            "issues": [
                {
                    "number": 1,
                    "title": "Mode hors ligne",
                    "body": "Il faut une PWA.",
                    "state": "OPEN",
                    "user": {"login": "ana"},
                    "updated_at": "2026-09-30T10:00:00Z",
                    "html_url": "https://github.com/exemple/orbit/issues/1",
                    "labels": [{"name": "décision"}],
                }
            ],
            "comments": {"1": [{"user": {"login": "bob"}, "body": "D'accord.", "created_at": "2026-09-30"}]},
            "pulls": [
                {
                    "number": 7,
                    "title": "Service worker",
                    "body": "Ajoute le cache.",
                    "state": "open",
                    "user": {"login": "carla"},
                    "updated_at": "2026-10-01T10:00:00Z",
                }
            ],
            "files": {
                "README.md": "# ORBIT fictif\n\nLisez-moi.",
                "docs/adr-001.md": "# ADR 001\n\nPWA retenue.",
            },
        },
    )
    seen: dict[str, str | None] = {}
    server = mcp_fake_server.build("github", str(fakes.path("github")), header_token=lambda: seen.get("auth"))
    app = server.streamable_http_app(
        streamable_http_path="/mcp/",
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    async def asgi(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            seen["auth"] = {k.decode(): v.decode() for k, v in scope["headers"]}.get("authorization")
            seen["toolsets"] = {k.decode(): v.decode() for k, v in scope["headers"]}.get("x-mcp-toolsets")
        await app(scope, receive, send)

    monkeypatch.setattr(mcp_client, "http_transport_override", httpx2.ASGITransport(app=asgi))
    body = {
        "type": "mcp",
        "name": "GitHub ORBIT",
        "config": {"preset": "github", "repos": ["exemple/orbit"], "docs_paths": ["README.md", "docs"]},
        "secret": json.dumps({"token": token}),
        "start_sync": True,
    }
    bad = await admin_client.post(
        base, json={**body, "config": {**body["config"], "repos": ["pas un dépôt"]}}
    )
    assert bad.status_code == 422 and "owner/nom" in bad.json()["detail"]
    async with server.session_manager.run():
        created = await admin_client.post(base, json=body)
        assert created.status_code == 201, created.text
        await _run_connector_jobs()
    run = await _last_run(admin_client, base, created.json()["id"])
    assert run["status"] == "succeeded", run
    docs = await _docs(created.json()["source_id"])
    assert set(docs) == {
        "issues:exemple/orbit#1",
        "pulls:exemple/orbit#7",
        "docs:exemple/orbit:README.md",
        "docs:exemple/orbit:docs/adr-001.md",
    }
    assert seen["auth"] == f"Bearer {token}" and seen["toolsets"] == "repos,issues,pull_requests,discussions"
    assert docs["issues:exemple/orbit#1"].uri == "https://github.com/exemple/orbit/issues/1"


async def test_custom_server_gating(
    admin_client: httpx.AsyncClient,
    project: JSON,
    fakes: Fakes,
    monkeypatch: pytest.MonkeyPatch,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    body = {
        "type": "mcp",
        "config": {"preset": "custom", "transport": "stdio", "command": "/opt/mcp/bin/fake-custom"},
        "secret": "{}",
    }
    disabled = await admin_client.post(f"{base}/test", json=body)
    assert disabled.status_code == 403 and disabled.json()["code"] == "mcp_custom_disabled"
    assert "custom" not in {t["preset"] for t in (await admin_client.get(f"{base}/types")).json()}

    monkeypatch.setattr(settings, "mcp_allow_custom", True)
    owner_user = await make_user()
    added = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": owner_user.email, "role": "owner"}
    )
    assert added.status_code == 201, added.text
    owner = await client_for(owner_user)
    forbidden = await owner.post(f"{base}/test", json=body)
    assert forbidden.status_code == 403 and forbidden.json()["code"] == "mcp_custom_forbidden"
    assert "custom" not in {t["preset"] for t in (await owner.get(f"{base}/types")).json()}

    allowed = await admin_client.post(f"{base}/test", json=body)
    assert allowed.status_code == 200 and allowed.json()["ok"] is True, allowed.text
    assert "custom" in {t["preset"] for t in (await admin_client.get(f"{base}/types")).json()}
    created = await admin_client.post(base, json={**body, "name": "Ressources", "start_sync": True})
    assert created.status_code == 201, created.text
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, created.json()["id"])
    assert (run["status"], run["created"]) == ("succeeded", 1), run
    http_ssrf = {
        **body,
        "config": {"preset": "custom", "transport": "http", "url": "https://interne.exemple.test/mcp"},
    }
    refused = await admin_client.post(f"{base}/test", json=http_ssrf)
    assert refused.status_code == 422 and "anti-SSRF" in refused.json()["detail"]


async def test_ms365_delta_files_and_deletions(
    admin_client: httpx.AsyncClient, project: JSON, fakes: Fakes
) -> None:
    base = _base(project)
    fakes.in_process.add("ms365")
    item = {
        "id": "it1",
        "name": "note-quai.md",
        "file": {"mimeType": "text/markdown"},
        "lastModifiedDateTime": "2026-09-30T10:00:00Z",
        "webUrl": "https://exemple.sharepoint.test/note",
    }
    fakes.write("ms365", {"drive_items": [item], "contents": {"it1": "# Quai B\n\nFermeture à 18 h."}})
    created = await admin_client.post(
        base,
        json={
            "type": "mcp",
            "name": "M365",
            "config": {"preset": "ms365", "drive_ids": ["b!drive1"]},
            "secret": json.dumps({"access_token": "graph-token-fictif-0001"}),
            "start_sync": True,
        },
    )
    assert created.status_code == 201, created.text
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, created.json()["id"])
    assert (run["status"], run["created"]) == ("succeeded", 1), run
    fakes.write(
        "ms365", {"drive_items": [{"id": "it1", "name": "note-quai.md", "deleted": {"state": "deleted"}}]}
    )
    await admin_client.post(f"{base}/{created.json()['id']}/sync")
    await _run_connector_jobs()
    run = await _last_run(admin_client, base, created.json()["id"])
    assert run["forgotten"] == 1, run


# --- MarkItDown fallback extractor --------------------------------------------------------------------


@pytest.fixture
def fake_markitdown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    wrapper = tmp_path / "markitdown-mcp"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" markitdown\n', encoding="utf-8")
    wrapper.chmod(0o755)
    monkeypatch.setattr(settings, "markitdown_mcp", "auto")
    monkeypatch.setattr(settings, "markitdown_mcp_command", str(wrapper))
    return wrapper


def test_markitdown_detection_and_switch(fake_markitdown: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert detect_mime_type("deck.pptx") == PPTX and needs_conversion(PPTX, "deck.pptx")
    assert is_supported(PPTX, "deck.pptx") and is_supported("image/png", "schema.png")
    assert not needs_conversion("text/csv", "crm.csv", b"a,b\n1,2")
    assert needs_conversion("application/vnd.ms-excel", "budget.xls", b"\xd0\xcf\x11\xe0rest")
    monkeypatch.setattr(settings, "markitdown_mcp", "off")
    assert not is_supported(PPTX, "deck.pptx") and is_supported("text/markdown", "a.md")
    assert "ORBIT_MARKITDOWN_MCP=off" in markitdown.unavailable_reason(PPTX, "deck.pptx")


async def test_markitdown_convert_and_unavailable(
    fake_markitdown: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    extracted = await markitdown.convert(b"PK\x03\x04 diapositives fictives", PPTX, "deck.pptx")
    assert (
        extracted.format == "markitdown" and "Diapositive 1" in extracted.text and ".pptx" in extracted.text
    )
    assert extracted.metadata["converter"] == "markitdown-mcp"
    monkeypatch.setattr(settings, "markitdown_mcp_command", "/nulle/part/markitdown-mcp")
    with pytest.raises(Exception) as caught:
        await markitdown.convert(b"PK", PPTX, "deck.pptx")
    assert "MarkItDown (MCP) indisponible" in str(caught.value)


async def test_markitdown_pipeline_upload(
    admin_client: httpx.AsyncClient, project: JSON, fake_markitdown: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = f"/api/v1/projects/{project['slug']}/documents/upload"
    files = [("files", ("revue-projet.pptx", b"PK\x03\x04 diapositives fictives", PPTX))]
    uploaded = await admin_client.post(upload, files=files, data={"acl_principals": "project:*"})
    assert uploaded.status_code == 201, uploaded.text
    [doc] = uploaded.json()
    await _drain_ingest()
    async with get_sessionmaker()() as session:
        document = await session.get(Document, doc["id"])
        assert document is not None and document.status != DocumentStatus.failed, document.status_reason
        job = await session.scalar(
            select(IngestionJob).where(
                IngestionJob.document_id == document.id, IngestionJob.kind == JobKind.ingest
            )
        )
        assert job is not None
        extract_step = next(s for s in job.steps if s["name"] == "extract")
        assert "MarkItDown" in extract_step["detail"] and "pptx" in extract_step["detail"]

    monkeypatch.setattr(settings, "markitdown_mcp", "off")
    refused = await admin_client.post(upload, files=files, data={"acl_principals": "project:*"})
    assert refused.status_code == 422 and "non pris en charge" in refused.json()["detail"]


async def test_connector_run_rows_keep_no_secret(
    admin_client: httpx.AsyncClient, project: JSON, fakes: Fakes
) -> None:
    """Error samples and run errors of a failing preset never contain the secret."""
    base = _base(project)
    fakes.write("atlassian", {**_atlassian_data(), "token": "autre-jeton"})
    created = await admin_client.post(base, json=_atlassian_body(start_sync=True))
    await _run_connector_jobs()
    async with get_sessionmaker()() as session:
        runs = list(
            await session.scalars(
                select(ConnectorRun).where(ConnectorRun.connector_id == created.json()["id"])
            )
        )
        assert runs and all(ATL_TOKEN not in json.dumps([r.error, r.error_samples, r.progress]) for r in runs)
        assert runs[0].status == "failed"
