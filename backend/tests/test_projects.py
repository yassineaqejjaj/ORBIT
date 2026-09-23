"""Projects: creation, listing with stats, access control, settings merge."""

from __future__ import annotations

import httpx

from app.services.projects import DEFAULT_PROJECT_SETTINGS
from tests.conftest import unique


async def test_create_project_with_generated_slug(admin_client: httpx.AsyncClient) -> None:
    name = f"Référentiel Atlas {unique('x')}"
    response = await admin_client.post("/api/v1/projects", json={"name": name, "description": "Démo"})
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["slug"].startswith("referentiel-atlas-")
    assert project["role"] == "owner"
    assert project["settings"] == DEFAULT_PROJECT_SETTINGS
    assert set(project) == {
        "id",
        "slug",
        "name",
        "description",
        "settings",
        "role",
        "created_at",
        "updated_at",
    }

    again = await admin_client.post("/api/v1/projects", json={"name": name})
    assert again.status_code == 201
    assert again.json()["slug"] == f"{project['slug']}-2"


async def test_explicit_slug_conflicts_and_reserved(admin_client: httpx.AsyncClient) -> None:
    slug = unique("atlas")
    assert (await admin_client.post("/api/v1/projects", json={"name": "A", "slug": slug})).status_code == 201
    conflict = await admin_client.post("/api/v1/projects", json={"name": "B", "slug": slug})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "conflict"
    reserved = await admin_client.post("/api/v1/projects", json={"name": "C", "slug": "new"})
    assert reserved.status_code == 409
    invalid = await admin_client.post("/api/v1/projects", json={"name": "D", "slug": "Pas Valide"})
    assert invalid.status_code == 422


async def test_list_projects_with_stats(admin_client: httpx.AsyncClient, project: dict) -> None:  # type: ignore[type-arg]
    response = await admin_client.get("/api/v1/projects")
    assert response.status_code == 200
    mine = next(p for p in response.json() if p["id"] == project["id"])
    assert mine["stats"] == {"sources": 0, "documents": 0, "memory_items": 0, "context_requests_7d": 0}
    assert mine["role"] == "owner"


async def test_members_only_see_their_projects(
    admin_client: httpx.AsyncClient,
    project: dict,
    make_user,
    client_for,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    outsider = await make_user()
    c = await client_for(outsider)
    assert (await c.get("/api/v1/projects")).json() == []
    denied = await c.get(f"/api/v1/projects/{project['slug']}")
    assert denied.status_code == 404
    assert denied.json() == {"detail": "Projet introuvable", "code": "not_found"}

    own = await c.post("/api/v1/projects", json={"name": "Projet perso"})
    assert own.status_code == 201
    listed = (await c.get("/api/v1/projects")).json()
    assert [p["id"] for p in listed] == [own.json()["id"]]


async def test_get_project_as_viewer(
    admin_client: httpx.AsyncClient,
    project: dict,
    make_user,
    client_for,  # type: ignore[no-untyped-def,type-arg]
) -> None:
    viewer = await make_user()
    added = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": viewer.email, "role": "viewer"}
    )
    assert added.status_code == 201
    c = await client_for(viewer)
    response = await c.get(f"/api/v1/projects/{project['slug']}")
    assert response.status_code == 200
    assert response.json()["role"] == "viewer"
    forbidden = await c.patch(f"/api/v1/projects/{project['slug']}", json={"name": "Piraté"})
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "forbidden"


async def test_patch_merges_settings(admin_client: httpx.AsyncClient, project: dict) -> None:  # type: ignore[type-arg]
    slug = project["slug"]
    response = await admin_client.patch(
        f"/api/v1/projects/{slug}",
        json={"name": "Projet renommé", "settings": {"freshness_days": {"ticket": 60}, "min_relevance": 0.4}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Projet renommé"
    assert body["settings"]["freshness_days"]["ticket"] == 60
    assert body["settings"]["freshness_days"]["document"] == 365
    assert body["settings"]["min_relevance"] == 0.4
    assert body["settings"]["default_token_budget"] == 4000
    assert body["updated_at"] >= project["updated_at"]

    second = await admin_client.patch(
        f"/api/v1/projects/{slug}", json={"settings": {"short_term_ttl_hours": 24}}
    )
    settings = second.json()["settings"]
    assert settings["freshness_days"]["ticket"] == 60
    assert settings["short_term_ttl_hours"] == 24

    persisted = (await admin_client.get(f"/api/v1/projects/{slug}")).json()
    assert persisted["settings"] == settings


async def test_patch_rejects_invalid_settings(admin_client: httpx.AsyncClient, project: dict) -> None:  # type: ignore[type-arg]
    for payload in (
        {"settings": {"min_relevance": 2}},
        {"settings": {"default_token_budget": 100}},
        {"settings": {"freshness_days": {"unknown_kind": 10}}},
        {"settings": {"other": 1}},
    ):
        response = await admin_client.patch(f"/api/v1/projects/{project['slug']}", json=payload)
        assert response.status_code == 422, payload


async def test_admin_is_owner_of_every_project(
    admin_client: httpx.AsyncClient,
    make_user,
    client_for,  # type: ignore[no-untyped-def]
) -> None:
    owner = await make_user()
    c = await client_for(owner)
    created = (await c.post("/api/v1/projects", json={"name": "Projet privé"})).json()
    response = await admin_client.get(f"/api/v1/projects/{created['slug']}")
    assert response.status_code == 200
    assert response.json()["role"] == "owner"
