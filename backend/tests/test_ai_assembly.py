"""Chantier C — assembly (docs/AI_CONTEXT_ENGINEERING.md §C): prompt cache, progressive mode, profiles,
learned compression, sufficiency. Fictitious demo data only; no network (hash embeddings, fake LLM)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.context import packaging, spotlight
from tests.test_api_documents import _text, drain
from tests.test_mcp_server import AgentSetup, agent_setup, error_text, mcp_client, payload  # noqa: F401

API = "/api/v1/projects"
JSON = dict[str, Any]


async def _memory(client: httpx.AsyncClient, slug: str, **body: Any) -> JSON:
    payload = {"scope": "project", "kind": "decision", "status": "validated", **body}
    response = await client.post(f"{API}/{slug}/memory", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _context(client: httpx.AsyncClient, slug: str, task: str, **extra: Any) -> JSON:
    response = await client.post(f"{API}/{slug}/context", json={"task": task, "min_relevance": 0, **extra})
    assert response.status_code == 200, response.text
    return response.json()


async def _seed(client: httpx.AsyncClient, slug: str) -> None:
    await _memory(
        client,
        slug,
        title="Check-in par QR code",
        content="Décision : le check-in du salon Atlas se fait par QR code sur le poste d'accueil.",
    )
    await _memory(
        client,
        slug,
        kind="constraint",
        title="Accessibilité RGAA AA",
        content="Contrainte : toutes les pages du parcours Atlas respectent le niveau RGAA AA.",
    )
    await _text(
        client,
        slug,
        title="Guide badge Atlas",
        content="Le badge Atlas est imprimé à l'accueil après le scan du QR code du visiteur.",
    )
    await _text(
        client,
        slug,
        title="Plan de salle Atlas",
        content="Le plan de salle Atlas répartit les exposants en trois halls numérotés.",
    )
    await drain()


# --- C1 prompt cache ---------------------------------------------------------------------------------


async def test_cache_prefix_stable_across_requests(
    admin_client: httpx.AsyncClient,
    project: JSON,
) -> None:
    slug = str(project["slug"])
    await _seed(admin_client, slug)
    first = await _context(admin_client, slug, "Comment fonctionne le check-in Atlas par QR code ?")
    second = await _context(
        admin_client, slug, "Quel est le plan de salle Atlas pour les exposants ?", cache_hints=True
    )
    stable_titles = {"Check-in par QR code", "Accessibilité RGAA AA"}
    for package in (first, second):
        titles = [i["title"] for i in package["items"]]
        assert stable_titles <= set(titles)
        # Stable items are cited first (S1, S2) and appear before the task, which closes the document.
        assert {i["citation"] for i in package["items"] if i["title"] in stable_titles} == {"S1", "S2"}
        assert package["context"].rstrip().endswith("._")
        assert package["cache_prefix_tokens"] > 0
    assert first["task"] != second["task"]
    assert first["cache_prefix_hash"] == second["cache_prefix_hash"]
    assert second["cache_prefix_reused"] is True
    assert first["cache_hints"] is None

    blocks = second["cache_hints"]
    assert [b["type"] for b in blocks] == ["text", "text"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"} and blocks[1]["cache_control"] is None
    assert "".join(b["text"] for b in blocks) == second["context"]
    assert blocks[0]["text"] == first["context"][: len(blocks[0]["text"])]
    assert "Check-in par QR code" in blocks[0]["text"] and second["task"] not in blocks[0]["text"]
    if spotlight.enabled():
        assert spotlight.OPEN in blocks[0]["text"] and spotlight.CLOSE in blocks[1]["text"]

    # A new stable item changes the prefix.
    await _memory(
        admin_client,
        slug,
        title="Badges imprimés sur place",
        content="Décision : les badges Atlas sont imprimés sur place, plus d'envoi postal.",
    )
    await drain()
    third = await _context(admin_client, slug, "Comment fonctionne le check-in Atlas par QR code ?")
    assert third["cache_prefix_hash"] != first["cache_prefix_hash"]
    assert third["cache_prefix_reused"] is False

    detail = await admin_client.get(f"{API}/{slug}/context/requests/{second['request_id']}")
    assert detail.json()["cache_prefix_hash"] == second["cache_prefix_hash"]
    metrics = (await admin_client.get(f"{API}/{slug}/metrics")).json()["cache"]
    assert metrics["packages"] >= 3 and metrics["reused"] >= 1 and 0 < metrics["reuse_rate"] < 1


def test_cache_header_is_request_independent() -> None:
    assert "{" not in packaging.CACHE_HEADER
    block = packaging.task_block("Tâche fictive", packaging.Intent.design)
    assert block.startswith("\n## Tâche") and "design" in block


# --- C2 progressive mode and on-demand tools ----------------------------------------------------------


async def test_progressive_mode_and_mcp_expansion_tools(
    app: Any,
    admin_client: httpx.AsyncClient,
    agent_setup: AgentSetup,  # noqa: F811
) -> None:
    slug = agent_setup.slug
    await _seed(admin_client, slug)
    secret = await _memory(
        admin_client,
        slug,
        title="Budget salon Atlas",
        content="Décision : le budget du salon Atlas est fixé à 90 000 euros.",
        classification=3,
    )
    private = await _memory(
        admin_client,
        slug,
        scope="user",
        kind="preference",
        title="Préférence personnelle",
        content="Préférence : réponses courtes en français.",
    )
    await drain()

    full = await _context(admin_client, slug, "check-in Atlas par QR code")
    package = await _context(admin_client, slug, "check-in Atlas par QR code", mode="progressive")
    assert package["mode"] == "progressive" and full["mode"] == "full"
    assert "## Résumé (contexte progressif)" in package["context"]
    assert "## Index des sources et décisions" in package["context"]
    assert all(i["tokens"] <= 40 for i in package["items"])  # teasers only
    index = {entry["title"]: entry for entry in package["index"]}
    decision = index["Check-in par QR code"]
    constraint = index["Accessibilité RGAA AA"]
    source = next(e for e in package["index"] if e["candidate_type"] == "chunk")
    assert decision["tool"] == "get_decision" and constraint["tool"] == "get_memory_item"
    assert source["tool"] == "expand_source"
    assert f"id={decision['id']} → get_decision" in package["context"]

    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        progressive = payload(
            await mcp.call_tool("get_context", {"task": "check-in Atlas par QR code", "mode": "progressive"})
        )
        assert progressive["mode"] == "progressive" and progressive["index"]
        got = payload(await mcp.call_tool("get_decision", {"decision_id": decision["id"]}))
        assert got["kind"] == "decision" and "QR code" in got["content"]
        if spotlight.enabled():
            assert got["content"].startswith(spotlight.OPEN) and got["untrusted_content_notice"]
        item = payload(await mcp.call_tool("get_memory_item", {"item_id": constraint["id"]}))
        assert item["kind"] == "constraint"
        wrong = await mcp.call_tool("get_decision", {"decision_id": constraint["id"]})
        assert "pas une décision" in error_text(wrong)
        expanded = payload(await mcp.call_tool("expand_source", {"source_id": source["id"]}))
        assert expanded["chunks"] == 1 and expanded["text"] and not expanded["truncated"]
        more = payload(await mcp.call_tool("search_more", {"query": "plan de salle exposants halls"}))
        assert more["results"] and all(r["expand_with"] for r in more["results"])
        ids = {r["id"] for r in more["results"]}
        assert secret["id"] not in ids and private["id"] not in ids  # governance: clearance, private scope
        # Denials (classification C3 > agent clearance, private user memory) answer like unknown ids.
        denied = [
            error_text(await mcp.call_tool("get_decision", {"decision_id": secret["id"]})),
            error_text(await mcp.call_tool("get_memory_item", {"item_id": private["id"]})),
            error_text(await mcp.call_tool("get_memory_item", {"item_id": str(uuid.uuid4())})),
            error_text(await mcp.call_tool("expand_source", {"source_id": str(uuid.uuid4())})),
        ]
        assert len({d.split(": ", 1)[1] for d in denied}) == 1 and "introuvable" in denied[0]

    audit = await admin_client.get(f"{API}/{slug}/audit", params={"action": "context.expand", "limit": 50})
    events = audit.json()["items"]
    outcomes = [e["details"].get("allowed") for e in events]
    assert outcomes.count(True) >= 4 and outcomes.count(False) >= 5
    reasons = {e["details"].get("reason_code") for e in events if e["details"].get("allowed") is False}
    assert {"EXCLUDED_CLASSIFICATION", "EXCLUDED_SCOPE"} <= reasons


# --- C3 context profiles per agent kind ---------------------------------------------------------------


async def test_context_profiles_applied_editable_and_suggested(
    admin_client: httpx.AsyncClient,
    agent_setup: AgentSetup,  # noqa: F811
    agent_client: Any,
) -> None:
    slug = agent_setup.slug
    await _seed(admin_client, slug)
    listed = (await admin_client.get(f"{API}/{slug}/context/profiles")).json()
    by_kind = {p["kind"]: p for p in listed}
    assert set(by_kind) == {"product", "design", "engineering", "research", "custom"}
    assert by_kind["engineering"]["token_budget"] == 6000 and not by_kind["engineering"]["customized"]
    assert by_kind["research"]["sections"][0] == "sources"

    edited = await admin_client.put(
        f"{API}/{slug}/context/profiles/product",
        json={"sections": ["constraints", "decisions"], "token_budget": 1500, "min_relevance": 0},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["customized"] is True and edited.json()["default"]["token_budget"] == 4000
    bad = await admin_client.put(f"{API}/{slug}/context/profiles/product", json={"sections": ["inconnue"]})
    assert bad.status_code == 422
    # Editing other project settings keeps the profiles.
    patched = await admin_client.patch(f"{API}/{slug}", json={"settings": {"default_token_budget": 3000}})
    assert patched.status_code == 200, patched.text

    # The product agent (MCP/REST key) gets its profile: budget, sections, order.
    async with agent_client(agent_setup.api_key) as agent:
        response = await agent.post(f"{API}/{slug}/context", json={"task": "check-in Atlas par QR code"})
    assert response.status_code == 200, response.text
    package = response.json()
    assert package["profile"]["kind"] == "product" and package["profile"]["customized"] is True
    assert package["token_budget"] == 1500
    assert {i["candidate_type"] for i in package["items"]} == {"memory"}
    assert package["exclusion_summary"].get("EXCLUDED_SCOPE", 0) >= 1
    context = package["context"]
    assert context.index("## Contraintes & risques") < context.index("## Décisions en vigueur")

    # Explorer « agir en tant que » applies the same profile and explains the exclusions.
    simulated = await _context(
        admin_client, slug, "check-in Atlas par QR code", agent_id=str(agent_setup.agent_id)
    )
    assert simulated["profile"]["kind"] == "product"
    assert any("hors du profil product" in e["reason_detail"] for e in simulated["excluded"])
    human = await _context(admin_client, slug, "check-in Atlas par QR code")
    assert human["profile"] is None and any(i["candidate_type"] == "chunk" for i in human["items"])

    # Feedback flagging served items as irrelevant suggests a stricter threshold.
    for _ in range(3):
        served = await _context(
            admin_client, slug, "check-in Atlas par QR code", agent_id=str(agent_setup.agent_id)
        )
        flags = [{"citation": i["citation"], "flag": "irrelevant"} for i in served["items"]]
        sent = await admin_client.post(
            f"{API}/{slug}/context/requests/{served['request_id']}/feedback",
            json={"rating": 2, "item_flags": flags},
        )
        assert sent.status_code in (200, 201), sent.text
    listed = {p["kind"]: p for p in (await admin_client.get(f"{API}/{slug}/context/profiles")).json()}
    suggestion = listed["product"]["suggestion"]
    assert suggestion["feedback_count"] == 3 and suggestion["avg_rating"] == 2
    assert suggestion["changes"]["min_relevance"] == 0.05 and suggestion["rationale"]
    assert listed["design"]["suggestion"]["changes"] == {}

    reset = await admin_client.delete(f"{API}/{slug}/context/profiles/product")
    assert reset.json()["customized"] is False and reset.json()["token_budget"] == 4000
