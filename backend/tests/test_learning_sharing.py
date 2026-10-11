"""Collective intelligence: a validated learning shared with other projects, within access rights."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from tests.conftest import UserInfo, unique

pytestmark = pytest.mark.asyncio

JSON = dict[str, Any]
EVIDENCE = {"runs": 12, "metric": "pass_rate", "baseline": 0.58, "candidate": 0.75, "experiment_id": "exp-1"}


async def _project(admin: httpx.AsyncClient) -> JSON:
    response = await admin.post(
        "/api/v1/projects", json={"name": f"Projet {unique('share')}", "description": "Projet de test"}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _join(admin: httpx.AsyncClient, project: JSON, user: UserInfo, role: str) -> None:
    added = await admin.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": user.email, "role": role}
    )
    assert added.status_code == 201, added.text


async def _learning(admin: httpx.AsyncClient, project: JSON, *, validate: bool = True, **over: Any) -> JSON:
    body = {
        "title": "Citer la règle métier",
        "content": "Citer la règle mot pour mot.",
        "evidence": EVIDENCE,
        **over,
    }
    created = await admin.post(f"/api/v1/projects/{project['slug']}/learnings", json=body)
    assert created.status_code == 201, created.text
    item = created.json()
    if validate:
        done = await admin.post(f"/api/v1/projects/{project['slug']}/memory/{item['id']}/validate", json={})
        assert done.status_code == 200, done.text
    return item


def _share(project: JSON, item: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/learnings/{item['id']}/share"


async def _proposals(client: httpx.AsyncClient, project: JSON) -> list[JSON]:
    return (await client.get(f"/api/v1/projects/{project['slug']}/learnings")).json()["items"]


async def test_an_editor_of_both_projects_shares_a_learning_as_an_independent_proposal(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    other = await _project(admin_client)
    alice = await make_user(clearance=1, name="Alice")
    await _join(admin_client, project, alice, "editor")
    await _join(admin_client, other, alice, "editor")
    item = await _learning(admin_client, project)
    alice_client = await client_for(alice)

    first = await alice_client.post(
        _share(project, item), json={"targets": [other["slug"]], "note": "Même domaine"}
    )
    assert first.status_code == 200, first.text
    (result,) = first.json()
    assert result["project"] == other["slug"] and result["status"] == "created"

    (copy,) = await _proposals(alice_client, other)
    assert copy["id"] == result["item_id"] and copy["status"] == "proposed" and copy["kind"] == "learning"
    assert copy["title"] == item["title"] and "shared" in copy["tags"] and copy["provenance_count"] == 1
    shared = copy["learning_meta"]["shared_from"]
    assert (
        shared["project"] == project["slug"]
        and shared["memory_id"] == item["id"]
        and shared["shared_by"] == "Alice"
    )
    assert copy["learning_meta"]["evidence"]["experiment_id"] == "exp-1"  # the proof travels with it
    # The source is untouched and sharing again is a no-op.
    assert (await _proposals(admin_client, project))[0]["status"] == "validated"
    again = await alice_client.post(_share(project, item), json={"targets": [other["slug"]]})
    assert again.json()[0]["status"] == "already_shared" and again.json()[0]["item_id"] == result["item_id"]
    assert len(await _proposals(alice_client, other)) == 1


async def test_sharing_is_all_or_nothing_and_needs_editor_rights_in_every_target(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    mine, reader_only, foreign = (
        await _project(admin_client),
        await _project(admin_client),
        await _project(admin_client),
    )
    bob = await make_user(clearance=1, name="Bob")
    await _join(admin_client, project, bob, "editor")
    await _join(admin_client, mine, bob, "editor")
    await _join(admin_client, reader_only, bob, "viewer")
    item = await _learning(admin_client, project)
    bob_client = await client_for(bob)

    viewer_target = await bob_client.post(
        _share(project, item), json={"targets": [mine["slug"], reader_only["slug"]]}
    )
    assert viewer_target.status_code == 403
    not_a_member = await bob_client.post(
        _share(project, item), json={"targets": [mine["slug"], foreign["slug"]]}
    )
    assert not_a_member.status_code == 404  # same answer as an unknown project: nothing leaks
    unknown = await bob_client.post(_share(project, item), json={"targets": ["nope-" + unique("x")]})
    assert unknown.status_code == 404
    assert await _proposals(admin_client, mine) == []  # nothing was created in the allowed project either


async def test_only_validated_open_low_classification_learnings_can_travel(
    admin_client: httpx.AsyncClient, project: JSON
) -> None:
    other = await _project(admin_client)
    proposed = await _learning(admin_client, project, validate=False, title="Pas encore validé")
    assert (
        await admin_client.post(_share(project, proposed), json={"targets": [other["slug"]]})
    ).status_code == 422
    confidential = await _learning(admin_client, project, title="Confidentiel", classification=2)
    refused = await admin_client.post(_share(project, confidential), json={"targets": [other["slug"]]})
    assert refused.status_code == 422 and "C2/C3" in refused.text
    plain = await _learning(admin_client, project, title="Partageable")
    assert (
        await admin_client.post(_share(project, plain), json={"targets": [project["slug"]]})
    ).status_code == 422
    assert (await admin_client.post(_share(project, plain), json={"targets": []})).status_code == 422
    assert (
        await admin_client.post(
            _share(project, {"id": "00000000-0000-4000-8000-000000000000"}), json={"targets": [other["slug"]]}
        )
    ).status_code == 404
    assert await _proposals(admin_client, other) == []


async def test_an_agent_key_cannot_share_across_projects(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[..., httpx.AsyncClient]
) -> None:
    other = await _project(admin_client)
    item = await _learning(admin_client, project)
    created = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/agents",
        json={"name": "FORGE", "kind": "engineering", "description": "Évaluation", "clearance": 1},
    )
    forge = agent_client(created.json()["api_key"])
    response = await forge.post(_share(project, item), json={"targets": [other["slug"]]})
    assert response.status_code in {401, 403}
    assert await _proposals(admin_client, other) == []
