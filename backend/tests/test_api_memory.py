"""Memory REST API (docs/API.md « Mémoire »): lifecycle endpoints, rights, privacy, graph."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from tests.conftest import UserInfo

JSON = dict[str, Any]


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/memory"


async def _create(client: httpx.AsyncClient, project: JSON, **overrides: Any) -> JSON:
    body: JSON = {
        "scope": "project",
        "kind": "decision",
        "title": "Check-in par QR code",
        "content": "Décision : check-in par QR code sur le poste.",
        "status": "validated",
    }
    body.update(overrides)
    response = await client.post(_base(project), json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _member(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
    role: str,
    clearance: int = 1,
) -> tuple[UserInfo, httpx.AsyncClient]:
    user = await make_user(clearance=clearance)
    added = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": user.email, "role": role}
    )
    assert added.status_code == 201, added.text
    return user, await client_for(user)


async def test_memory_lifecycle_endpoints(admin_client: httpx.AsyncClient, project: JSON) -> None:
    base = _base(project)
    item = await _create(admin_client, project)
    assert item["status"] == "validated"
    assert item["version"] == 1 and item["is_current"] is True
    assert item["created_by_type"] == "user" and item["created_by_label"]

    patched = await admin_client.patch(
        f"{base}/{item['id']}", json={"content": "Décision : check-in par QR code affiché sur chaque poste."}
    )
    assert patched.status_code == 200, patched.text
    v2 = patched.json()
    assert v2["version"] == 2 and v2["lineage_id"] == item["lineage_id"] and v2["id"] != item["id"]

    listed = (await admin_client.get(base, params={"q": "QR code"})).json()
    lineage_rows = [i for i in listed["items"] if i["lineage_id"] == item["lineage_id"]]
    assert [i["version"] for i in lineage_rows] == [2]
    history = (await admin_client.get(base, params={"q": "QR code", "include_history": "true"})).json()
    assert {i["version"] for i in history["items"] if i["lineage_id"] == item["lineage_id"]} == {1, 2}

    detail = (await admin_client.get(f"{base}/{item['id']}")).json()
    assert detail["item"]["id"] == v2["id"]  # an old version id resolves to its detail
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    events = {e["event"] for e in detail["history"]}
    assert {"created", "edited"} <= events
    assert all(e["actor_label"] for e in detail["history"])
    assert detail["provenance"] == [] or isinstance(detail["provenance"], list)

    missing_reason = await admin_client.post(f"{base}/{v2['id']}/obsolete", json={})
    assert missing_reason.status_code == 422
    obsolete = await admin_client.post(f"{base}/{v2['id']}/obsolete", json={"reason": "Abandonné"})
    assert obsolete.status_code == 200 and obsolete.json()["status"] == "obsolete"
    again = await admin_client.post(f"{base}/{v2['id']}/validate", json={})
    assert again.status_code == 409
    assert again.json()["code"] == "conflict"
    restored = await admin_client.post(f"{base}/{v2['id']}/restore", json={"reason": "Erreur"})
    assert restored.status_code == 200 and restored.json()["status"] in {"validated", "proposed"}

    forgotten = await admin_client.post(f"{base}/{v2['id']}/forget", json={"reason": "Demande RGPD"})
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten.json()["status"] == "forgotten"
    assert forgotten.json()["content"] == "[oublié]"
    refused = await admin_client.post(f"{base}/{v2['id']}/validate", json={})
    assert refused.status_code == 409
    assert "oublié" in refused.json()["detail"]


async def test_supersede_and_graph(admin_client: httpx.AsyncClient, project: JSON) -> None:
    base = _base(project)
    old = await _create(
        admin_client,
        project,
        title="Login email et mot de passe",
        content="Décision : connexion par email et mot de passe.",
        valid_from="2026-06-01T09:00:00Z",
    )
    new = await _create(
        admin_client,
        project,
        title="Authentification SSO OIDC",
        content="Décision : authentification SSO OIDC (Keycloak).",
        valid_from="2026-09-01T09:00:00Z",
    )
    response = await admin_client.post(
        f"{base}/{old['id']}/supersede", json={"by_id": new["id"], "reason": "Décision du comité"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "superseded"
    assert response.json()["superseded_by_id"] == new["id"]

    detail = (await admin_client.get(f"{base}/{new['id']}")).json()
    supersedes = [r for r in detail["relations"] if r["rel_type"] == "supersedes"]
    assert supersedes and supersedes[0]["direction"] == "out"
    assert supersedes[0]["other_id"] == old["id"]
    assert supersedes[0]["other_title"] == "Login email et mot de passe"

    graph = (await admin_client.get(f"{base}/graph")).json()
    node_ids = {n["id"] for n in graph["nodes"]}
    assert {old["id"], new["id"]} <= node_ids
    assert any(
        e["source"] == new["id"] and e["target"] == old["id"] and e["rel_type"] == "supersedes"
        for e in graph["edges"]
    )

    self_replace = await admin_client.post(f"{base}/{new['id']}/supersede", json={"by_id": new["id"]})
    assert self_replace.status_code == 409


async def test_consolidate_enqueues_job(admin_client: httpx.AsyncClient, project: JSON) -> None:
    first = await admin_client.post(f"{_base(project)}/consolidate")
    assert first.status_code == 200, first.text
    job = first.json()
    assert job["kind"] == "consolidate" and job["status"] in {"queued", "running", "succeeded"}
    second = await admin_client.post(f"{_base(project)}/consolidate")
    assert second.status_code == 200
    if job["status"] == "queued":
        assert second.json()["id"] == job["id"]  # no duplicate pending job


async def test_agent_items_are_always_proposed(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[[str], httpx.AsyncClient]
) -> None:
    created = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/agents",
        json={"name": "Agent QA", "kind": "engineering", "description": "Tests", "clearance": 1},
    )
    assert created.status_code == 201, created.text
    agent = agent_client(created.json()["api_key"])
    item = await _create(agent, project, title="Tests de charge", status="validated")
    assert item["status"] == "proposed"
    assert item["created_by_type"] == "agent"
    assert item["created_by_label"] == "Agent QA"
    # Agents are not accepted on user-only endpoints.
    listing = await agent.get(_base(project))
    assert listing.status_code in {401, 403}


async def test_user_memory_is_private_to_its_subject(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    alice, alice_client = await _member(admin_client, project, make_user, client_for, "editor")
    _bob, bob_client = await _member(admin_client, project, make_user, client_for, "editor")
    pref = await _create(
        alice_client,
        project,
        scope="user",
        kind="preference",
        title="Réponses concises",
        content="Préfère des réponses concises avec des listes à puces.",
    )
    assert pref["subject_user_id"] == str(alice.id)
    assert pref["acl_principals"] == [f"user:{alice.id}"]

    mine = (await alice_client.get(base, params={"scope": "user"})).json()
    assert [i["id"] for i in mine["items"]] == [pref["id"]]
    # Neither another member nor the project owner / platform admin can see it.
    for other in (bob_client, admin_client):
        assert (await other.get(base, params={"scope": "user"})).json()["total"] == 0
        assert (await other.get(f"{base}/{pref['id']}")).status_code == 404
        assert (await other.post(f"{base}/{pref['id']}/forget", json={"reason": "x"})).status_code == 404

    for_someone_else = await alice_client.post(
        base,
        json={
            "scope": "user",
            "kind": "preference",
            "title": "Préférence imposée",
            "content": "Préfère les tableaux.",
            "subject_user_id": str(_bob.id),
        },
    )
    assert for_someone_else.status_code == 403

    forgotten = await alice_client.post(f"{base}/{pref['id']}/forget", json={"reason": "RGPD"})
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten.json()["status"] == "forgotten"


async def test_classification_and_roles(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    secret = await _create(
        admin_client, project, title="Budget confidentiel", content="Le budget est de 2 M€.", classification=2
    )
    _viewer, viewer_client = await _member(
        admin_client, project, make_user, client_for, "viewer", clearance=1
    )
    _editor, editor_client = await _member(
        admin_client, project, make_user, client_for, "editor", clearance=1
    )

    listed = (await viewer_client.get(base)).json()
    assert secret["id"] not in {i["id"] for i in listed["items"]}
    assert (await viewer_client.get(f"{base}/{secret['id']}")).status_code == 404

    public = await _create(admin_client, project, title="Pilote à Lyon", content="Décision : pilote à Lyon.")
    assert (await viewer_client.get(f"{base}/{public['id']}")).status_code == 200
    denied = await viewer_client.patch(f"{base}/{public['id']}", json={"title": "Pilote à Paris"})
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"

    too_high = await editor_client.post(
        base,
        json={
            "scope": "project",
            "kind": "fact",
            "title": "Secret",
            "content": "Secret.",
            "classification": 3,
        },
    )
    assert too_high.status_code == 403
    not_owner = await editor_client.post(f"{base}/{public['id']}/forget", json={"reason": "Test"})
    assert not_owner.status_code == 403
