"""Project audit trail."""

from __future__ import annotations

import uuid

import httpx

from app.db import get_sessionmaker
from app.services import audit


async def test_actions_are_audited(admin_client: httpx.AsyncClient, project: dict, make_user) -> None:  # type: ignore[no-untyped-def,type-arg]
    slug = project["slug"]
    user = await make_user()
    await admin_client.post(f"/api/v1/projects/{slug}/members", json={"email": user.email, "role": "viewer"})
    await admin_client.post(
        f"/api/v1/projects/{slug}/agents", json={"name": "Agent", "kind": "research", "clearance": 1}
    )

    response = await admin_client.get(f"/api/v1/projects/{slug}/audit")
    assert response.status_code == 200
    page = response.json()
    assert page["page"] == 1 and page["page_size"] == 25
    actions = [e["action"] for e in page["items"]]
    assert actions[:3] == ["agent.create", "member.add", "project.create"]
    assert page["total"] == 3
    first = page["items"][0]
    assert first["actor_type"] == "user"
    assert first["actor_label"] == "Administrateur ORBIT"

    filtered = (await admin_client.get(f"/api/v1/projects/{slug}/audit", params={"action": "member"})).json()
    assert [e["action"] for e in filtered["items"]] == ["member.add"]

    paged = (
        await admin_client.get(f"/api/v1/projects/{slug}/audit", params={"page": 2, "page_size": 2})
    ).json()
    assert len(paged["items"]) == 1 and paged["total"] == 3


async def test_restricted_details_hidden_from_non_owners(
    admin_client: httpx.AsyncClient,
    project: dict,
    make_user,
    client_for,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    project_id = uuid.UUID(project["id"])
    async with get_sessionmaker()() as session:
        await audit.record(
            session,
            project_id,
            None,
            "context.request",
            "context_request",
            uuid.uuid4(),
            summary="Contexte servi",
            details={"included": 5, "restricted": {"excluded_titles": ["Salaires 2026"]}},
        )
        await session.commit()

    viewer = await make_user()
    await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": viewer.email, "role": "viewer"}
    )
    viewer_items = (await (await client_for(viewer)).get(f"/api/v1/projects/{project['slug']}/audit")).json()[
        "items"
    ]
    event = next(e for e in viewer_items if e["action"] == "context.request")
    assert event["details"] == {"included": 5}
    assert event["actor_type"] == "system"

    owner_items = (await admin_client.get(f"/api/v1/projects/{project['slug']}/audit")).json()["items"]
    event = next(e for e in owner_items if e["action"] == "context.request")
    assert event["details"]["restricted"] == {"excluded_titles": ["Salaires 2026"]}
