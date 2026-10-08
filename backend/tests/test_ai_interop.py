"""Chantier E — interoperability (docs/AI_CONTEXT_ENGINEERING.md §E4–E6): MCP resources / prompts /
elicitation, A2A Agent Card and signed handoffs, OpenTelemetry GenAI attributes. Fictitious data only."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp_types import ElicitResult

from tests.test_ai_eval import memory
from tests.test_feature_llm import FakeLLM, fake_llm  # noqa: F401
from tests.test_mcp_server import AgentSetup, agent_setup  # noqa: F401

API = "/api/v1/projects"
JSON = dict[str, Any]


@asynccontextmanager
async def mcp(app: FastAPI, key: str, **kwargs: Any) -> AsyncIterator[Client]:
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-Orbit-Key": key},
        timeout=30,
    )
    async with (
        http,
        Client(streamable_http_client("http://testserver/mcp", http_client=http), **kwargs) as client,
    ):
        yield client


def _text(result: Any) -> str:
    return result.contents[0].text


# --- E4 MCP resources, prompts, elicitation ---------------------------------------------------------


async def test_mcp_resources_are_listed_and_governed(
    app: FastAPI,
    admin_client: httpx.AsyncClient,
    agent_setup: AgentSetup,  # noqa: F811
) -> None:
    slug = agent_setup.slug
    public = await memory(
        admin_client, slug, title="Hébergement Atlas", content="Atlas est hébergé chez OVH."
    )
    await memory(
        admin_client,
        slug,
        title="Décision secrète Atlas",
        content="Rachat envisagé du prestataire.",
        classification=3,
    )
    await memory(
        admin_client,
        slug,
        kind="procedure",
        title="Revue de code Atlas",
        content="Chaque pull request doit être relue par deux développeurs avant fusion.",
        skill_meta={"description": "Règle de revue de code"},
    )
    snap = await admin_client.post(
        f"{API}/{slug}/context",
        json={"task": "Hébergement Atlas", "min_relevance": 0, "save_snapshot": {"name": "spec-atlas"}},
    )
    assert snap.status_code == 200, snap.text

    async with mcp(app, agent_setup.api_key) as client:
        static = await client.list_resources()
        assert [str(r.uri) for r in static.resources] == ["orbit://about"]
        templates = {t.uri_template for t in (await client.list_resource_templates()).resource_templates}
        assert {
            "orbit://decisions{?limit}",
            "orbit://snapshots/{name}/{version}",
            "orbit://skills/{name}",
        } <= templates

        decisions = json.loads(_text(await client.read_resource("orbit://decisions")))
        titles = [d["title"] for d in decisions["decisions"]]
        assert "Hébergement Atlas" in titles
        assert "Décision secrète Atlas" not in titles  # C3 above the agent's clearance (C2)
        assert "untrusted" in json.dumps(decisions).lower() or "non fiable" in json.dumps(decisions)
        one = json.loads(_text(await client.read_resource(f"orbit://decisions/{public['lineage_id']}")))
        assert "OVH" in json.dumps(one, ensure_ascii=False)

        snapshots = json.loads(_text(await client.read_resource("orbit://snapshots")))
        assert [s["name"] for s in snapshots["snapshots"]] == ["spec-atlas"]
        snapshot = json.loads(_text(await client.read_resource("orbit://snapshots/spec-atlas/latest")))
        assert snapshot["name"] == "spec-atlas"
        skills = json.loads(_text(await client.read_resource("orbit://skills")))
        name = skills["skills"][0]["name"]
        skill_md = _text(await client.read_resource(f"orbit://skills/{name}"))
        assert skill_md.startswith("---") and "deux développeurs" in skill_md
        with pytest.raises(MCPError, match="introuvable"):
            await client.read_resource("orbit://snapshots/absent/latest")


async def test_mcp_prompts_and_elicitation(
    app: FastAPI,
    admin_client: httpx.AsyncClient,
    agent_setup: AgentSetup,  # noqa: F811
) -> None:
    await memory(
        admin_client, agent_setup.slug, title="Hébergement Atlas", content="Atlas est hébergé chez OVH."
    )
    asked: list[str] = []

    async def on_elicit(_context: Any, params: Any) -> ElicitResult:
        asked.append(params.message)
        return ElicitResult(action="accept", content={"sujet": "hébergement Atlas"})

    async with mcp(app, agent_setup.api_key, mode="legacy") as client:
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        assert prompts == {"rediger_spec", "preparer_revue", "resumer_changements"}
        spec = await client.get_prompt("rediger_spec", {"sujet": "hébergement Atlas"})
        assert "OVH" in spec.messages[0].content.text and "[S1]" in spec.messages[0].content.text
        changes = await client.get_prompt("resumer_changements", {"jours": "7"})
        assert "Hébergement Atlas" in changes.messages[0].content.text
        fallback = await client.get_prompt(
            "preparer_revue", {}
        )  # legacy client: no elicitation, default subject
        assert "décisions et changements récents" in fallback.messages[0].content.text

    async with mcp(app, agent_setup.api_key, mode="2026-07-28", elicitation_callback=on_elicit) as client:
        review = await client.get_prompt("preparer_revue", {})
        assert asked == ["Sur quel sujet porte la revue ?"]
        assert "« hébergement Atlas »" in review.messages[0].content.text


# --- E5 A2A -----------------------------------------------------------------------------------------


async def test_agent_card_is_served(client: httpx.AsyncClient) -> None:
    for path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
        response = await client.get(path)
        assert response.status_code == 200, response.text
        card = response.json()
        assert card["protocolVersion"] == "0.3.0" and card["name"] == "ORBIT"
        assert card["url"].endswith("/api/v1") and card["preferredTransport"] == "HTTP+JSON"
        assert {s["id"] for s in card["skills"]} == {"governed-context", "project-memory", "context-handoff"}
        assert "orbitAgentKey" in card["securitySchemes"]


async def test_signed_handoff_valid_invalid_and_replay(
    admin_client: httpx.AsyncClient,
    agent_client: Any,
    agent_setup: AgentSetup,  # noqa: F811
) -> None:
    import jwt

    from app.api.a2a import sign

    slug = agent_setup.slug
    await memory(admin_client, slug, title="Hébergement Atlas", content="Atlas est hébergé chez OVH.")
    saved = await admin_client.post(
        f"{API}/{slug}/context",
        json={"task": "Hébergement Atlas", "min_relevance": 0, "save_snapshot": {"name": "handoff-atlas"}},
    )
    assert saved.status_code == 200, saved.text
    second = await admin_client.post(
        f"{API}/{slug}/agents", json={"name": "Agent Revue", "kind": "engineering", "clearance": 1}
    )
    assert second.status_code == 201, second.text
    receiver_id = second.json()["agent"]["id"]
    sender = agent_client(agent_setup.api_key)
    receiver = agent_client(second.json()["api_key"])

    issued = await sender.post(
        f"{API}/{slug}/a2a/handoffs", json={"snapshot": "handoff-atlas@1", "audience": f"agent:{receiver_id}"}
    )
    assert issued.status_code == 201, issued.text
    token = issued.json()["token"]
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "HS256" and header["typ"] == "orbit-context-handoff+jwt"

    wrong_receiver = await sender.post(f"{API}/{slug}/a2a/handoffs/receive", json={"token": token})
    assert wrong_receiver.status_code == 403
    head, payload, signature = token.split(".")
    tampered = f"{head}.{payload}.{signature[:-4]}AAAA"
    assert (
        await receiver.post(f"{API}/{slug}/a2a/handoffs/receive", json={"token": tampered})
    ).status_code == 401
    forged = jwt.encode(
        jwt.decode(token, options={"verify_signature": False}),
        "autre-secret-0123456789abcdef0123456789",
        "HS256",
    )
    assert (
        await receiver.post(f"{API}/{slug}/a2a/handoffs/receive", json={"token": forged})
    ).status_code == 401

    received = await receiver.post(f"{API}/{slug}/a2a/handoffs/receive", json={"token": token})
    assert received.status_code == 200, received.text
    body = received.json()
    assert body["verified"] is True and body["snapshot"]["name"] == "handoff-atlas"
    assert body["issuer"] == f"agent:{agent_setup.agent_id}"
    replay = await receiver.post(f"{API}/{slug}/a2a/handoffs/receive", json={"token": token})
    assert replay.status_code == 409 and "rejeu" in replay.text

    claims = jwt.decode(token, options={"verify_signature": False})
    expired = sign({**claims, "jti": "expired-jti", "iat": claims["iat"] - 7200, "exp": claims["iat"] - 3600})
    assert (
        await receiver.post(f"{API}/{slug}/a2a/handoffs/receive", json={"token": expired})
    ).status_code == 401

    audit = (await admin_client.get(f"{API}/{slug}/audit", params={"action": "a2a", "limit": 50})).json()
    items = audit.get("items", audit) if isinstance(audit, dict) else audit
    actions = [a["action"] for a in items]
    assert actions.count("a2a.handoff_issue") == 1 and actions.count("a2a.handoff_receive") == 1
    assert actions.count("a2a.handoff_reject") == 5


# --- E6 OpenTelemetry GenAI semantic conventions ----------------------------------------------------


async def test_genai_attributes_on_llm_retrieval_and_mcp_spans(
    app: FastAPI,
    admin_client: httpx.AsyncClient,
    agent_setup: AgentSetup,  # noqa: F811
    fake_llm: Any,  # noqa: F811
) -> None:
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app.llm import client as llm_client
    from app.observability.tracing import setup_tracing

    exporter = InMemorySpanExporter()
    setup_tracing().add_span_processor(SimpleSpanProcessor(exporter))

    def spans(name_prefix: str) -> list[Any]:
        return [s for s in exporter.get_finished_spans() if s.name.startswith(name_prefix)]

    fake_llm(lambda _p: "Bonjour")
    assert await llm_client.complete("Système", "Dis bonjour", classification=0, max_tokens=50) == "Bonjour"
    chat = spans("chat ")[-1]
    assert chat.attributes["gen_ai.operation.name"] == "chat"
    assert chat.attributes["gen_ai.provider.name"] == "anthropic"
    assert chat.attributes["gen_ai.request.max_tokens"] == 50
    assert chat.attributes["gen_ai.usage.input_tokens"] >= 0 and "gen_ai.response.model" in chat.attributes
    assert "gen_ai.input.messages" not in chat.attributes  # content capture is off by default

    slug = agent_setup.slug
    await memory(admin_client, slug, title="Hébergement Atlas", content="Atlas est hébergé chez OVH.")
    await admin_client.post(f"{API}/{slug}/context", json={"task": "Hébergement Atlas", "min_relevance": 0})
    retrieve = spans("context.retrieve")[-1]
    assert retrieve.attributes["gen_ai.operation.name"] == "retrieval"
    assert retrieve.attributes["gen_ai.data_source.id"] == f"orbit:{slug}"
    assert retrieve.attributes["orbit.retrieval.hits"] >= 1

    async with mcp(app, agent_setup.api_key) as client:
        await client.call_tool("list_skills", {})
        await client.read_resource("orbit://decisions")
    tool = spans("tools/call list_skills")[-1]
    assert tool.attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool.attributes["gen_ai.tool.name"] == "list_skills"
    assert tool.attributes["gen_ai.agent.id"] == str(agent_setup.agent_id)
    assert tool.attributes["mcp.method.name"] == "tools/call"
    read = spans("resources/read")[-1]
    assert read.attributes["mcp.resource.uri"] == "orbit://decisions"
    assert read.attributes["gen_ai.agent.name"] == "Agent Produit"
