"""Live context events: ``context.served`` change events, webhook opt-in, no content leak, SSE stream."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import orjson
import pytest
from fastapi import FastAPI

from app.api import events as stream_api
from app.config import settings
from app.context import retrieval
from app.enums import JobKind
from app.features.feed import security
from app.features.feed.service import FeedViewer
from app.features.live import bus
from app.governance.acl import PROJECT_ALL
from tests.conftest import UserInfo
from tests.test_ai_eval import API as EVAL_API
from tests.test_ai_eval import run_jobs, seed_decisions
from tests.test_feature_webhooks import Receiver, _hook, receiver  # noqa: F401

JSON = dict[str, Any]
SECRET_TASK = "Quel est le montant confidentiel QZX-4471 du contrat Orion ?"
SECRET_TITLE = "Clause confidentielle QZX-4471"
SECRET_BODY = "Décision : le montant confidentiel QZX-4471 du contrat Orion est de douze millions."


@pytest.fixture(autouse=True)
def _fulltext(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _unavailable(*_a: Any, **_k: Any) -> list[retrieval.IndexHit]:
        raise retrieval.RetrievalUnavailable("tests: index désactivé")

    monkeypatch.setattr(retrieval, "search_index", _unavailable)


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}"


async def _secret(client: httpx.AsyncClient, project: JSON, classification: int = 2) -> JSON:
    response = await client.post(
        f"{_base(project)}/memory",
        json={
            "scope": "project",
            "kind": "decision",
            "title": SECRET_TITLE,
            "content": SECRET_BODY,
            "status": "validated",
            "classification": classification,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _agent(
    client: httpx.AsyncClient, project: JSON, name: str = "Agent Produit", clearance: int = 2
) -> JSON:
    created = await client.post(
        f"{_base(project)}/agents", json={"name": name, "kind": "product", "clearance": clearance}
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _serve(client: httpx.AsyncClient, project: JSON, task: str = SECRET_TASK) -> JSON:
    response = await client.post(f"{_base(project)}/context", json={"task": task})
    assert response.status_code == 200, response.text
    return response.json()


async def _served_events(client: httpx.AsyncClient, project: JSON) -> list[JSON]:
    await bus.drain()
    response = await client.get(f"{_base(project)}/changes", params={"types": "context.served"})
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def test_rest_context_emits_event_without_content(
    admin_client: httpx.AsyncClient, agent_client: Callable[..., httpx.AsyncClient], project: JSON
) -> None:
    await _secret(client := admin_client, project)
    agent = await _agent(client, project)
    package = await _serve(agent_client(agent["api_key"]), project)
    assert package["items"], "the secret decision should be served"
    (event,) = await _served_events(client, project)
    assert event["type"] == "context.served" and event["type_label"] == "Contexte servi"
    assert event["title"] == "Contexte servi à Agent Produit"
    data = event["data"]
    assert data["request_id"] == package["request_id"] and data["agent_id"] == agent["agent"]["id"]
    assert data["agent_name"] == "Agent Produit" and data["count"] == 1
    assert data["included_count"] >= 1 and data["tokens_used"] > 0 and data["max_classification"] == 2
    assert event["classification"] == 2
    assert "on_behalf_of" not in data  # user scope details are never exposed by the API
    dump = json.dumps(event, ensure_ascii=False)
    for forbidden in ("QZX-4471", "Orion", "montant", SECRET_TITLE, SECRET_TASK):
        assert forbidden not in dump


async def test_event_hidden_above_clearance(
    admin_client: httpx.AsyncClient,
    agent_client: Callable[..., httpx.AsyncClient],
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    await _secret(admin_client, project, classification=2)
    agent = await _agent(admin_client, project)
    await _serve(agent_client(agent["api_key"]), project)
    low = await make_user(clearance=1)
    added = await admin_client.post(f"{_base(project)}/members", json={"email": low.email, "role": "viewer"})
    assert added.status_code == 201, added.text
    low_client = await client_for(low)
    assert len(await _served_events(admin_client, project)) == 1
    assert await _served_events(low_client, project) == []
    # a public context (C0) is visible to every member
    await _serve(agent_client(agent["api_key"]), project, task="Question sans rapport avec aucun document")
    assert len(await _served_events(admin_client, project)) >= 1


async def test_coalescing_counter(
    admin_client: httpx.AsyncClient,
    agent_client: Callable[..., httpx.AsyncClient],
    project: JSON,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "context_events_coalesce_seconds", 60)
    await _secret(admin_client, project, classification=0)
    first, second = (
        await _agent(admin_client, project, "Agent A"),
        await _agent(admin_client, project, "Agent B"),
    )
    for _ in range(3):
        await _serve(agent_client(first["api_key"]), project)
    await _serve(agent_client(second["api_key"]), project)
    events = await _served_events(admin_client, project)
    counts = {e["data"]["agent_name"]: e["data"]["count"] for e in events}
    assert counts == {"Agent A": 3, "Agent B": 1}
    summary = next(e["summary"] for e in events if e["data"]["agent_name"] == "Agent A")
    assert summary.startswith("3 contextes servis à Agent A")


async def test_coalescing_disabled_and_feature_switch(
    admin_client: httpx.AsyncClient,
    agent_client: Callable[..., httpx.AsyncClient],
    project: JSON,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _secret(admin_client, project, classification=0)
    agent = await _agent(admin_client, project)
    monkeypatch.setattr(settings, "context_events_coalesce_seconds", 0)
    for _ in range(2):
        await _serve(agent_client(agent["api_key"]), project)
    assert len(await _served_events(admin_client, project)) == 2
    monkeypatch.setattr(settings, "context_events", False)
    await _serve(agent_client(agent["api_key"]), project)
    assert len(await _served_events(admin_client, project)) == 2


async def test_human_request_is_grouped_under_the_explorer(
    admin_client: httpx.AsyncClient, project: JSON
) -> None:
    await _secret(admin_client, project, classification=0)
    await _serve(admin_client, project)
    (event,) = await _served_events(admin_client, project)
    assert event["title"] == "Contexte servi à l'Explorateur"


async def test_evaluation_runs_emit_no_event(admin_client: httpx.AsyncClient, project: JSON) -> None:
    slug = str(project["slug"])
    decisions = await seed_decisions(admin_client, slug)
    created = await admin_client.post(f"{EVAL_API}/{slug}/evaluation/sets", json={"name": "Ref"})
    set_id = created.json()["id"]
    await admin_client.post(
        f"{EVAL_API}/{slug}/evaluation/sets/{set_id}/cases",
        json={
            "question": "Où est hébergé le portail Atlas ?",
            "expected": [{"type": "memory", "id": decisions[0]["lineage_id"], "title": "Hébergement"}],
        },
    )
    started = await admin_client.post(f"{EVAL_API}/{slug}/evaluation/sets/{set_id}/runs", json={"k": 5})
    assert started.status_code == 202, started.text
    assert await run_jobs(JobKind.evaluate) == 1
    assert await _served_events(admin_client, project) == []


async def test_mcp_get_context_emits_event(
    app: FastAPI, admin_client: httpx.AsyncClient, project: JSON
) -> None:
    from tests.test_mcp_server import mcp_client

    await _secret(admin_client, project, classification=1)
    agent = await _agent(admin_client, project)
    async with mcp_client(app, {"X-Orbit-Key": agent["api_key"]}) as mcp:
        result = await mcp.call_tool("get_context", {"task": SECRET_TASK})
    assert not result.is_error
    (event,) = await _served_events(admin_client, project)
    assert event["data"]["agent_name"] == "Agent Produit"
    assert "QZX-4471" not in json.dumps(event, ensure_ascii=False)


async def test_webhook_opt_in_signature_and_no_content(
    admin_client: httpx.AsyncClient,
    agent_client: Callable[..., httpx.AsyncClient],
    project: JSON,
    receiver: Receiver,  # noqa: F811
) -> None:
    from tests.test_feature_webhooks import _run_webhook_jobs

    await _secret(admin_client, project, classification=1)
    agent = await _agent(admin_client, project)
    default_hook = await _hook(admin_client, project)  # no types: context.served is NOT delivered
    await _serve(agent_client(agent["api_key"]), project)
    assert await _run_webhook_jobs() == 0
    patched = await admin_client.patch(
        f"{_base(project)}/webhooks/{default_hook['id']}", json={"types": ["context.served"]}
    )
    assert patched.status_code == 200, patched.text
    await _serve(agent_client(agent["api_key"]), project, task="Une autre question à propos du contrat")
    # coalesced into the first event (default window): force a distinct event with another agent
    other = await _agent(admin_client, project, "Agent B")
    await _serve(agent_client(other["api_key"]), project)
    assert await _run_webhook_jobs() == 1
    (request,) = receiver.requests
    assert request.headers["X-Orbit-Event"] == "context.served"
    body = request.content
    assert request.headers["X-Orbit-Signature"] == security.sign(default_hook["secret"], body)
    payload = orjson.loads(body)
    assert payload["type"] == "context.served" and payload["data"]["agent_id"] == other["agent"]["id"]
    assert "actor" not in payload and payload["data"]["included_count"] >= 1
    text = body.decode()
    for forbidden in ("QZX-4471", "Orion", "montant", SECRET_TITLE, "autre question"):
        assert forbidden not in text


async def test_webhook_accepts_the_new_type_and_digest_off_by_default(
    admin_client: httpx.AsyncClient,
    project: JSON,
    receiver: Receiver,  # noqa: F811
) -> None:
    hook = await _hook(admin_client, project, types=["context.served"])
    assert hook["types"] == ["context.served"]
    await _secret(admin_client, project, classification=0)
    await _serve(admin_client, project)
    default = await admin_client.get(f"{_base(project)}/changes/digest", params={"period": "day"})
    assert all(g["type"] != "context.served" for g in default.json()["groups"])
    saved = await admin_client.put(
        f"{_base(project)}/subscriptions/me", json={"digest": "daily", "types": ["context.served"]}
    )
    assert saved.status_code == 200, saved.text
    asked = await admin_client.get(f"{_base(project)}/changes/digest", params={"period": "day"})
    assert [g["type"] for g in asked.json()["groups"]] == ["context.served"]
    from tests.test_feature_webhooks import _run_webhook_jobs

    await _run_webhook_jobs()  # leave no queued delivery behind (encrypted with this test's key)


# --- SSE ---------------------------------------------------------------------------------------------


class FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


def _viewer(clearance: int = 1) -> FeedViewer:
    return FeedViewer(uuid.uuid4(), frozenset({PROJECT_ALL}), clearance)


async def _frames(
    project_id: Any,
    viewer: FeedViewer,
    *,
    last_id: int | None = None,
    limit: int = 3,
    timeout: float = 5,
    until: str = "",
):  # type: ignore[no-untyped-def]
    out: list[str] = []

    async def read() -> None:
        async for chunk in stream_api._events(FakeRequest(), project_id, viewer, last_id):  # type: ignore[arg-type]
            out.append(chunk.decode())
            if len(out) >= limit or (until and until in out[-1]):
                return

    await asyncio.wait_for(read(), timeout)
    return out


async def test_sse_heartbeat_visibility_and_ids_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "live_stream_heartbeat_seconds", 0.1)
    viewer = _viewer(clearance=1)
    pid = viewer.project_id

    async def publish_later() -> None:
        await asyncio.sleep(0.3)
        await bus.publish(pid, "context.served", {"request_id": "r1", "agent_id": "a1"}, classification=3)
        await bus.publish(pid, "memory.changed", {"memory_id": "m1"}, classification=0)
        await bus.publish(pid, "memory.changed", {"memory_id": "m2"}, classification=0, acl=["team:x"])

    task = asyncio.create_task(publish_later())
    frames = await _frames(pid, viewer, limit=40, until='"m1"')
    await task
    text = "".join(frames)
    assert ": ping" in text  # heartbeat
    assert "event: memory.changed" in text and '"memory_id":"m1"' in text
    assert "r1" not in text and "m2" not in text  # above clearance / outside the ACL


async def test_sse_resume_with_last_event_id() -> None:
    viewer = _viewer()
    pid = viewer.project_id
    first = await bus.publish(pid, "snapshot.created", {"snapshot_id": "s1"})
    second = await bus.publish(pid, "snapshot.created", {"snapshot_id": "s2"})
    assert first and second and second > first
    frames = await _frames(pid, viewer, last_id=first, limit=2)
    text = "".join(frames)
    assert "s2" in text and "s1" not in text


async def test_sse_degrades_when_valkey_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def pubsub(self) -> Any:
            raise ConnectionError("valkey down")

    monkeypatch.setattr("app.memory.short_term.get_valkey", lambda: Broken())
    frames = await _frames(uuid.uuid4(), _viewer(), limit=2)
    assert "event: degraded" in "".join(frames)
    assert await bus.publish(uuid.uuid4(), "memory.changed", {"memory_id": "x"}) is None  # no-op, no crash


async def test_sse_endpoint_auth_headers_and_limits(
    admin_client: httpx.AsyncClient,
    project: JSON,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    url = f"{_base(project)}/events/stream"
    anonymous = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    async with anonymous:
        assert (await anonymous.get(url)).status_code == 401
    stranger = await client_for(await make_user())
    assert (await stranger.get(url)).status_code in (403, 404)

    monkeypatch.setattr(
        stream_api, "MAX_STREAM_SECONDS", 0
    )  # the stream ends right away: ASGITransport buffers
    response = await admin_client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in response.headers["cache-control"] and response.headers["x-accel-buffering"] == "no"
    assert ": connected" in response.text and "event: reconnect" in response.text

    monkeypatch.setattr(settings, "live_stream_max_connections_per_user", 1)
    stream_api._per_user.update({next(iter([f"user:{u}" for u in [0]])): 0})
    monkeypatch.setattr(stream_api, "_total", 0)
    # per-user limit: pretend the user already holds a stream
    me = (await admin_client.get("/api/v1/auth/me")).json()
    stream_api._per_user[f"user:{me['id']}"] = 1
    try:
        limited = await admin_client.get(url)
        assert limited.status_code == 429
    finally:
        stream_api._per_user.clear()
    monkeypatch.setattr(settings, "live_stream", False)
    assert (await admin_client.get(url)).status_code == 404
