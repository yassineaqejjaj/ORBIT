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
