"""Chantier C — assembly (docs/AI_CONTEXT_ENGINEERING.md §C): prompt cache, progressive mode, profiles,
learned compression, sufficiency. Fictitious demo data only; no network (hash embeddings, fake LLM)."""

from __future__ import annotations

from typing import Any

import httpx

from app.context import packaging, spotlight
from tests.test_api_documents import _text, drain

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
