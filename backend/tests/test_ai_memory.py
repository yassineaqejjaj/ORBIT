"""Chantier D — memory (docs/AI_CONTEXT_ENGINEERING.md §D): procedures as skills, « tel que connu au »,
entities and aliases, model-based contradictions, monthly reflection. Fictitious demo data only; no
network (hash embeddings, fake LLM through MockTransport, stub NLI)."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.memory import skills
from app.memory.extractor import classify_sentence
from tests.test_api_documents import drain
from tests.test_mcp_server import AgentSetup, agent_setup, mcp_client, payload  # noqa: F401

API = "/api/v1/projects"
JSON = dict[str, Any]

DOD = (
    "Une user story Atlas est terminée quand : les critères d'acceptation sont vérifiés, les tests "
    "automatisés passent, la revue de code est faite et la documentation utilisateur est à jour."
)


async def _memory(client: httpx.AsyncClient, slug: str, **body: Any) -> JSON:
    data = {"scope": "project", "kind": "decision", "status": "validated", **body}
    response = await client.post(f"{API}/{slug}/memory", json=data)
    assert response.status_code == 201, response.text
    return response.json()


async def _context(client: httpx.AsyncClient, slug: str, task: str, **extra: Any) -> JSON:
    response = await client.post(f"{API}/{slug}/context", json={"task": task, "min_relevance": 0, **extra})
    assert response.status_code == 200, response.text
    return response.json()


async def _procedure(client: httpx.AsyncClient, slug: str, **meta: Any) -> JSON:
    return await _memory(
        client,
        slug,
        kind="procedure",
        title="Définition de terminé d'une user story",
        content=DOD,
        skill_meta={"description": "Critères pour déclarer une user story terminée", **meta},
    )


# --- D1 procedural memory / skills --------------------------------------------------------------------


def test_procedural_statements_are_extracted() -> None:
    for sentence in (
        DOD,
        "Chaque pull request doit être relue par deux développeurs avant fusion.",
        "Convention : les branches sont nommées feature/<ticket>.",
    ):
        statement = classify_sentence(sentence)
        assert statement is not None and statement.kind.value == "procedure", sentence
    constraint = classify_sentence("Le budget du salon doit rester sous 90 000 euros.")
    assert constraint is not None and constraint.kind.value == "constraint"
    assert (
        skills.slugify("Définition de terminé d'une user story") == "definition-de-termine-d-une-user-story"
    )


async def test_skills_crud_skill_md_and_zip(admin_client: httpx.AsyncClient, project: JSON) -> None:
    slug = str(project["slug"])
    created = await _procedure(admin_client, slug, task_types=["specification"], agent_kinds=["product"])
    meta = created["skill_meta"]
    assert meta["name"] == "definition-de-termine-d-une-user-story"
    assert meta["task_types"] == ["specification"] and meta["agent_kinds"] == ["product"]

    listed = (await admin_client.get(f"{API}/{slug}/skills")).json()
    assert [s["name"] for s in listed] == [meta["name"]]
    detail = (await admin_client.get(f"{API}/{slug}/skills/{meta['name']}")).json()
    md = detail["skill_md"]
    assert md.startswith("---\nname: definition-de-termine-d-une-user-story\ndescription: ")
    assert "  task_types: [specification]" in md and "# Définition de terminé" in md and DOD in md

    # Edit = new version (metadata kept, renamed skill).
    edited = await admin_client.patch(
        f"{API}/{slug}/memory/{created['id']}",
        json={"skill_meta": {"name": "dod-user-story", "task_types": ["specification", "validation"]}},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2 and edited.json()["skill_meta"]["name"] == "dod-user-story"
    assert (await admin_client.get(f"{API}/{slug}/skills/{meta['name']}")).status_code == 404

    download = await admin_client.get(f"{API}/{slug}/skills/dod-user-story/download")
    assert download.status_code == 200 and download.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert archive.namelist() == ["dod-user-story/SKILL.md"]
        assert "name: dod-user-story" in archive.read("dod-user-story/SKILL.md").decode()

    # Skill names follow the Agent Skills format (kebab-case).
    bad = await admin_client.post(
        f"{API}/{slug}/memory",
        json={
            "scope": "project",
            "kind": "procedure",
            "title": "x",
            "content": "y",
            "skill_meta": {"name": "A B"},
        },
    )
    assert bad.status_code == 422


async def test_skills_mcp_and_context_injection(
    app: Any,
    admin_client: httpx.AsyncClient,
    agent_setup: AgentSetup,  # noqa: F811
) -> None:
    slug = agent_setup.slug
    await _procedure(admin_client, slug, task_types=["specification"], agent_kinds=["product"])
    await _memory(
        admin_client,
        slug,
        kind="procedure",
        title="Checklist de mise en production",
        content="Avant de déployer Atlas : sauvegarde, migration testée, plan de retour arrière.",
        skill_meta={"agent_kinds": ["engineering"]},
    )
    await _memory(
        admin_client,
        slug,
        title="Check-in par QR code",
        content="Décision : le check-in du salon Atlas se fait par QR code.",
    )
    await drain()

    # Product agent writing a specification: the DoD is anchored in « Façons de faire »; the
    # engineering-only checklist is excluded with an explained reason.
    package = await _context(
        admin_client,
        slug,
        "Rédiger la spécification de la user story check-in Atlas",
        intent="specification",
        agent_id=str(agent_setup.agent_id),
        explain=True,
    )
    assert "## Façons de faire" in package["context"]
    titles = {i["title"] for i in package["items"]}
    assert "Définition de terminé d'une user story" in titles
    assert "Checklist de mise en production" not in titles
    excluded = {e["title"]: e for e in package["excluded"]}
    if "Checklist de mise en production" in excluded:
        assert excluded["Checklist de mise en production"]["reason_code"] == "EXCLUDED_SCOPE"

    async with mcp_client(app, {"X-Orbit-Key": agent_setup.api_key}) as mcp:
        listed = payload(await mcp.call_tool("list_skills", {}))
        names = {s["name"] for s in listed["skills"]}
        assert {"definition-de-termine-d-une-user-story", "checklist-de-mise-en-production"} <= names
        filtered = payload(await mcp.call_tool("list_skills", {"task_type": "specification"}))
        assert {s["name"] for s in filtered["skills"]} == {"definition-de-termine-d-une-user-story"}
        skill = payload(await mcp.call_tool("get_skill", {"name": "definition-de-termine-d-une-user-story"}))
        assert skill["skill_md"].startswith("---\nname: definition-de-termine-d-une-user-story")


# --- D2 temporal facts ----------------------------------------------------------------------------------


async def test_as_of_memory_list_and_context(admin_client: httpx.AsyncClient, project: JSON) -> None:
    slug = str(project["slug"])
    now = datetime.now(UTC)
    old = await _memory(
        admin_client,
        slug,
        kind="fact",
        title="Capacité du hall Atlas",
        content="Fait : le hall principal Atlas accueille 800 visiteurs.",
        valid_from=(now - timedelta(days=60)).isoformat(),
        valid_to=(now - timedelta(days=10)).isoformat(),
    )
    current = await _memory(
        admin_client,
        slug,
        kind="fact",
        title="Capacité du hall Atlas (agrandi)",
        content="Fait : le hall principal Atlas accueille 1200 visiteurs.",
        valid_from=(now - timedelta(days=10)).isoformat(),
    )
    await drain()

    past = (now - timedelta(days=30)).isoformat()
    # Items are created now: « known at » a past date only shows versions created by then.
    listed = (await admin_client.get(f"{API}/{slug}/memory", params={"as_of": past})).json()
    assert listed["total"] == 0
    later = datetime.now(UTC).isoformat()
    listed = (await admin_client.get(f"{API}/{slug}/memory", params={"as_of": later})).json()
    ids = {i["id"] for i in listed["items"]}
    assert current["id"] in ids and old["id"] not in ids  # validity window honoured

    # Edit after a reference date: the reference date still sees version 1.
    reference = datetime.now(UTC)
    edited = await admin_client.patch(
        f"{API}/{slug}/memory/{current['id']}",
        json={"content": "Fait : le hall principal Atlas accueille 1500 visiteurs."},
    )
    assert edited.status_code == 200
    listed = (await admin_client.get(f"{API}/{slug}/memory", params={"as_of": reference.isoformat()})).json()
    versions = {i["title"]: i["version"] for i in listed["items"]}
    assert versions["Capacité du hall Atlas (agrandi)"] == 1

    package = await _context(
        admin_client,
        slug,
        "Capacité du hall principal Atlas",
        as_of=reference.isoformat(),
        include_sources=False,
    )
    texts = " ".join(i["excerpt"] for i in package["items"] if i["candidate_type"] == "memory")
    assert "1200" in texts and "1500" not in texts and "800" not in texts
    assert any("telle que connue au" in w for w in package["warnings"])


# --- D2 entity resolution -------------------------------------------------------------------------------


async def test_entity_merge_unmerge_audited_and_aliases_in_retrieval(
    admin_client: httpx.AsyncClient, project: JSON
) -> None:
    slug = str(project["slug"])
    full = await admin_client.post(f"{API}/{slug}/entities", json={"name": "Application Mobile Exposants"})
    short = await admin_client.post(f"{API}/{slug}/entities", json={"name": "AME", "kind": "produit"})
    other = await admin_client.post(f"{API}/{slug}/entities", json={"name": "Badge visiteur"})
    assert full.status_code == short.status_code == other.status_code == 201, full.text
    dup = await admin_client.post(f"{API}/{slug}/entities", json={"name": "ame"})
    assert dup.status_code == 409

    suggestions = (await admin_client.get(f"{API}/{slug}/entities/suggestions")).json()
    assert len(suggestions) == 1
    pair = {suggestions[0]["a"]["name"], suggestions[0]["b"]["name"]}
    assert pair == {"Application Mobile Exposants", "AME"} and "sigle" in suggestions[0]["reason"]

    target, source = full.json()["id"], short.json()["id"]
    merged = await admin_client.post(f"{API}/{slug}/entities/{target}/merge", json={"source_id": source})
    assert merged.status_code == 200, merged.text
    assert {a["alias"] for a in merged.json()["aliases"]} == {"Application Mobile Exposants", "AME"}
    listed = (await admin_client.get(f"{API}/{slug}/entities")).json()
    assert {e["name"] for e in listed} == {"Application Mobile Exposants", "Badge visiteur"}
    assert (await admin_client.get(f"{API}/{slug}/entities/suggestions")).json() == []

    await _memory(
        admin_client,
        slug,
        kind="fact",
        title="Disponibilité de l'application mobile exposants",
        content="Fait : l'Application Mobile Exposants est disponible sur iOS et Android depuis mars.",
    )
    await _memory(
        admin_client,
        slug,
        kind="fact",
        title="Parking",
        content="Fait : le parking du salon compte 400 places.",
    )
    await drain()
    task = "Sur quelles plateformes l'AME est-elle publiée ?"
    package = await _context(admin_client, slug, task, include_sources=False)
    assert "Disponibilité de l'application mobile exposants" in {i["title"] for i in package["items"]}
    graph = (await admin_client.get(f"{API}/{slug}/memory/graph")).json()
    entity_nodes = [n for n in graph["nodes"] if n["type"] == "entity"]
    assert [n["label"] for n in entity_nodes] == ["Application Mobile Exposants"]
    assert any(e["target"] == target and e["rel_type"] == "mentions" for e in graph["edges"])

    # The alias query is the extra retrieval query of round 1.
    queries = [q for r in package["timings"]["rounds"] for q in r["queries"]]
    assert any("Application Mobile Exposants" in str(q) for q in queries)

    unmerged = await admin_client.post(f"{API}/{slug}/entities/{source}/unmerge", json={"reason": "erreur"})
    assert unmerged.status_code == 200 and [a["alias"] for a in unmerged.json()["aliases"]] == ["AME"]
    again = await admin_client.post(f"{API}/{slug}/entities/{source}/unmerge", json={})
    assert again.status_code == 409
    audit = (await admin_client.get(f"{API}/{slug}/audit", params={"limit": 50})).json()
    actions = {entry["action"] for entry in audit["items"]}
    assert {"entity.create", "entity.merge", "entity.unmerge"} <= actions
