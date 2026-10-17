"""Workspace isolation (ADR 001 §9, NOV-106): two workspaces, two modes.

Fixture: workspaces A and B, each with an owner, a platform-style admin, a project, one agent key and the
**same** document text (same title, same content: only the project differs). ``ORBIT_WORKSPACE_ENFORCEMENT``
is switched per test:

* ``off``     — historical behaviour (a stale cross-workspace membership still works), nothing counted;
* ``shadow``  — same answers as ``off``, every cross-workspace access counted in
  ``orbit_workspace_violations_total``;
* ``enforce`` — another workspace answers 404, **indistinguishable** from an unknown id; search, context,
  prompt-cache reuse, organisation memory, lists, members, users and webhook payloads leak nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import pytest_asyncio
from prometheus_client import REGISTRY
from sqlalchemy import select, update

from app.config import settings
from app.db import get_sessionmaker
from app.enums import MemoryKind, MemoryScope
from app.memory import lifecycle, short_term
from app.models import Agent, Project, ProjectMember, User, Workspace
from app.models.memory import MemoryItem
from app.schemas.memory import MemoryIn
from app.search import opensearch
from app.services import workspaces
from app.services.audit import Actor
from app.services.users import create_user
from tests.conftest import DEFAULT_PASSWORD, UserInfo, unique
from tests.test_api_documents import _text, drain
from tests.test_feature_webhooks import _decision, _hook, _run_webhook_jobs, receiver  # noqa: F401

API = "/api/v1/projects"
SHARED_TITLE = "Procédure de rotation des badges"
SHARED_BODY = "La rotation des badges d'accès se fait chaque trimestre par le service sûreté."


@dataclass
class Space:
    workspace_id: uuid.UUID
    owner: UserInfo
    admin: UserInfo
    owner_client: httpx.AsyncClient
    admin_client: httpx.AsyncClient
    project: dict[str, Any]
    document_id: str
    agent_key: str
    agent_id: uuid.UUID

    @property
    def slug(self) -> str:
        return str(self.project["slug"])

    @property
    def project_id(self) -> uuid.UUID:
        return uuid.UUID(str(self.project["id"]))


def set_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setattr(settings, "workspace_enforcement", mode)


def violations(mode: str, surface: str) -> float:
    return (
        REGISTRY.get_sample_value("orbit_workspace_violations_total", {"mode": mode, "surface": surface})
        or 0.0
    )


async def _user(workspace_id: uuid.UUID, *, clearance: int = 2, is_admin: bool = False) -> UserInfo:
    email = f"{unique('ws')}@example.com"
    async with get_sessionmaker()() as session:
        user = await create_user(
            session,
            email=email,
            full_name=f"Compte {email.split('@')[0]}",
            password=DEFAULT_PASSWORD,
            clearance=clearance,
            is_admin=is_admin,
            workspace_id=workspace_id,
        )
        await session.commit()
        return UserInfo(id=user.id, email=email, password=DEFAULT_PASSWORD, full_name=user.full_name)


async def _space(name: str, client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]]) -> Space:
    async with get_sessionmaker()() as session:
        workspace = Workspace(name=f"{name} {unique('espace')}")
        session.add(workspace)
        await session.commit()
        workspace_id = workspace.id
    owner = await _user(workspace_id)
    admin = await _user(workspace_id, clearance=3, is_admin=True)
    owner_client = await client_for(owner)
    admin_client = await client_for(admin)
    created = await owner_client.post(API, json={"name": f"Projet {name} {unique('p')}"})
    assert created.status_code == 201, created.text
    project = created.json()
    document = await _text(owner_client, str(project["slug"]), title=SHARED_TITLE, content=SHARED_BODY)
    agent = await owner_client.post(
        f"{API}/{project['slug']}/agents",
        json={"name": f"agent-{name}", "kind": "engineering", "clearance": 1},
    )
    assert agent.status_code == 201, agent.text
    return Space(
        workspace_id=workspace_id,
        owner=owner,
        admin=admin,
        owner_client=owner_client,
        admin_client=admin_client,
        project=project,
        document_id=str(document["id"]),
        agent_key=agent.json()["api_key"],
        agent_id=uuid.UUID(agent.json()["agent"]["id"]),
    )


@pytest_asyncio.fixture
async def spaces(
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> tuple[Space, Space]:
    a = await _space("A", client_for)
    b = await _space("B", client_for)
    await drain()
    await opensearch.refresh()
    return a, b


# --- Identity and inheritance ----------------------------------------------------------------------------------


async def test_a_project_inherits_the_workspace_of_its_creator_and_exposes_orion_project_id(
    spaces: tuple[Space, Space],
) -> None:
    a, b = spaces
    assert a.workspace_id != b.workspace_id
    for space in spaces:
        detail = (await space.owner_client.get(f"{API}/{space.slug}")).json()
        assert "workspace_id" not in detail  # the workspace is not part of the API contract (identity-bound)
        assert detail["orion_project_id"] == detail["id"]  # backfilled / defaulted to the project's own id
    async with get_sessionmaker()() as session:
        for space in spaces:
            row = await session.get(Project, space.project_id)
            assert row is not None and row.workspace_id == space.workspace_id  # inherited from the creator
    async with get_sessionmaker()() as session:
        agent = await session.get(Agent, a.agent_id)
        assert (
            agent is not None and agent.workspace_id == a.workspace_id
        )  # a key belongs to its project's space


async def test_the_workspace_is_immutable_and_never_a_request_parameter(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = spaces
    async with get_sessionmaker()() as session:
        project = await session.get(Project, a.project_id)
        assert project is not None
        project.workspace_id = b.workspace_id
        with pytest.raises(ValueError, match="workspace_id"):
            await session.flush()
        await session.rollback()
        project = await session.get(Project, a.project_id)
        assert project is not None
        project.orion_project_id = uuid.uuid4()
        with pytest.raises(ValueError, match="orion_project_id"):
            await session.flush()
        await session.rollback()
    # a body / query / header naming another workspace changes nothing (unknown fields are refused or ignored)
    set_mode(monkeypatch, "enforce")
    created = await a.admin_client.post(
        "/api/v1/users",
        json={
            "email": f"{unique('x')}@example.com",
            "full_name": "Nouveau compte",
            "password": DEFAULT_PASSWORD,
            "clearance": 1,
            "workspace_id": str(b.workspace_id),
        },
        headers={"X-Orion-Workspace": str(b.workspace_id)},
    )
    if created.status_code == 201:
        assert created.json().get("workspace_id") in (None, str(a.workspace_id))
        async with get_sessionmaker()() as session:
            user = await session.scalar(select(User).where(User.email == created.json()["email"]))
            assert user is not None and user.workspace_id == a.workspace_id
    else:
        assert created.status_code == 422


# --- enforce: 404 indistinguishable --------------------------------------------------------------------------


async def test_enforce_another_workspace_is_indistinguishable_from_an_unknown_project(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = spaces
    set_mode(monkeypatch, "enforce")
    unknown = await b.owner_client.get(f"{API}/{unique('inexistant')}")
    assert unknown.status_code == 404
    paths = [
        ("GET", ""),
        ("GET", "/documents"),
        ("GET", f"/documents/{a.document_id}"),
        ("GET", "/search?q=badges"),
        ("GET", "/members"),
        ("GET", "/webhooks"),
        ("GET", "/agents"),
        ("GET", "/memory"),
        ("GET", "/snapshots"),
    ]
    for method, suffix in paths:
        other = await b.owner_client.request(method, f"{API}/{a.slug}{suffix}")
        reference = await b.owner_client.request(method, f"{API}/{unique('inexistant')}{suffix}")
        assert other.status_code == reference.status_code == 404, (suffix, other.text)
        assert other.json() == reference.json(), suffix  # same body: nothing tells "exists elsewhere"
    posted = await b.owner_client.post(f"{API}/{a.slug}/context", json={"task": "rotation des badges"})
    assert posted.status_code == 404 and posted.json() == unknown.json()
    # a platform admin of B does not cross either (ADR §9 invariant 4), nor does a B owner's delete
    assert (await b.admin_client.get(f"{API}/{a.slug}")).status_code == 404
    write = await b.owner_client.post(f"{API}/{a.slug}/documents/text", json={"title": "x", "content": "y"})
    assert write.status_code == 404 and write.json() == unknown.json()  # writes are refused the same way
    # ... while each space keeps working for its own members
    assert (await a.owner_client.get(f"{API}/{a.slug}")).status_code == 200
    assert (await b.admin_client.get(f"{API}/{b.slug}")).status_code == 200


async def test_enforce_a_stale_cross_workspace_membership_is_refused_off_serves_it_shadow_counts_it(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = spaces
    async with get_sessionmaker()() as session:  # B's owner was (wrongly) made a member of A's project
        session.add(ProjectMember(project_id=a.project_id, user_id=b.owner.id, role="viewer"))
        await session.commit()
    url = f"{API}/{a.slug}"

    set_mode(monkeypatch, "off")
    before = (violations("shadow", "project"), violations("enforce", "project"))
    assert (await b.owner_client.get(url)).status_code == 200  # historical behaviour, byte for byte
    assert (violations("shadow", "project"), violations("enforce", "project")) == before  # nothing evaluated

    set_mode(monkeypatch, "shadow")
    assert (await b.owner_client.get(url)).status_code == 200  # served...
    assert violations("shadow", "project") == before[0] + 1  # ...and counted
    assert (await b.owner_client.get(f"{API}/{b.slug}")).status_code == 200  # own workspace: not counted
    assert violations("shadow", "project") == before[0] + 1

    set_mode(monkeypatch, "enforce")
    assert (await b.owner_client.get(url)).status_code == 404
    assert violations("enforce", "project") == before[1] + 1


async def test_enforce_lists_only_the_projects_of_the_callers_workspace(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = spaces
    async with get_sessionmaker()() as session:
        session.add(ProjectMember(project_id=a.project_id, user_id=b.owner.id, role="viewer"))
        await session.commit()
    set_mode(monkeypatch, "off")
    off = {p["slug"] for p in (await b.owner_client.get(API)).json()}
    assert {a.slug, b.slug} <= off
    set_mode(monkeypatch, "enforce")
    assert {p["slug"] for p in (await b.owner_client.get(API)).json()} == {b.slug}
    admin_view = {p["slug"] for p in (await b.admin_client.get(API)).json()}
    assert b.slug in admin_view and a.slug not in admin_view


async def test_enforce_agent_key_of_another_workspace_and_a_key_whose_space_differs_from_its_project(
    spaces: tuple[Space, Space],
    monkeypatch: pytest.MonkeyPatch,
    agent_client: Callable[..., httpx.AsyncClient],
) -> None:
    a, b = spaces
    set_mode(monkeypatch, "enforce")
    key_a = agent_client(a.agent_key)
    body = {"task": "rotation des badges"}
    assert (await key_a.post(f"{API}/{b.slug}/context", json=body)).status_code == 404  # key A on project B
    assert (await key_a.post(f"{API}/{a.slug}/context", json=body)).status_code == 200
    # a key stored with another workspace than its project's (inconsistent data) is refused on its own project
    async with get_sessionmaker()() as session:
        await session.execute(update(Agent).where(Agent.id == a.agent_id).values(workspace_id=b.workspace_id))
        await session.commit()
    assert (await key_a.post(f"{API}/{a.slug}/context", json=body)).status_code == 404
    set_mode(monkeypatch, "shadow")
    assert (await key_a.post(f"{API}/{a.slug}/context", json=body)).status_code == 200
    set_mode(monkeypatch, "off")
    assert (await key_a.post(f"{API}/{a.slug}/context", json=body)).status_code == 200


# --- enforce: search, context, cache --------------------------------------------------------------------------


async def test_enforce_search_and_context_never_return_the_other_workspaces_content(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = spaces
    for mode in ("off", "enforce"):  # the isolation of the index filter does not depend on the mode
        set_mode(monkeypatch, mode)
        for mine, other in ((a, b), (b, a)):
            hits = (
                await mine.owner_client.get(f"{API}/{mine.slug}/search", params={"q": "rotation des badges"})
            ).json()
            assert hits and {h["document_id"] for h in hits} == {mine.document_id}, mode
            package = await mine.owner_client.post(
                f"{API}/{mine.slug}/context", json={"task": "Comment tourne la rotation des badges ?"}
            )
            assert package.status_code == 200, package.text
            body = package.json()
            assert body["items"], mode
            assert {i["document_id"] for i in body["items"]} == {mine.document_id}, mode
            assert other.document_id not in str(body)
            assert body["orion_project_id"] == str(mine.project_id)


async def test_enforce_the_prompt_cache_prefix_is_never_reused_from_another_workspace(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = spaces
    set_mode(monkeypatch, "enforce")
    task = {"task": "Comment tourne la rotation des badges ?", "mode": "full"}
    first_a = (await a.owner_client.post(f"{API}/{a.slug}/context", json=task)).json()
    second_a = (await a.owner_client.post(f"{API}/{a.slug}/context", json=task)).json()
    first_b = (await b.owner_client.post(f"{API}/{b.slug}/context", json=task)).json()
    assert first_a["cache_prefix_hash"] and not first_a["cache_prefix_reused"]
    assert second_a["cache_prefix_reused"]  # within a project, the identical prefix is reused
    assert first_b["cache_prefix_hash"] == first_a["cache_prefix_hash"]  # same text on purpose...
    assert not first_b["cache_prefix_reused"]  # ...yet nothing is reused across spaces


async def test_the_short_term_and_live_keys_carry_the_project(spaces: tuple[Space, Space]) -> None:
    a, b = spaces
    assert str(a.project_id) in short_term.session_key(a.project_id, "s1")
    assert short_term.session_key(a.project_id, "s1") != short_term.session_key(b.project_id, "s1")
    from app.features.live import bus

    assert str(a.project_id) in bus._log_key(a.project_id)
    assert bus._log_key(a.project_id) != bus._log_key(b.project_id)


@pytest_asyncio.fixture
async def org_memory() -> AsyncIterator[str]:
    """One organisation-wide long-term item (project_id NULL: belongs to the default workspace)."""
    token = f"orgtoken{uuid.uuid4().hex[:10]}"
    async with get_sessionmaker()() as session:
        item = await lifecycle.create_item(
            session,
            project_id=None,
            data=MemoryIn(
                scope=MemoryScope.long_term,
                kind=MemoryKind.fact,
                title=f"Charte {token}",
                content=f"La charte d'organisation {token} impose la rotation trimestrielle des badges.",
                status="validated",
            ),
            actor=Actor.system(),
        )
        await session.commit()
        item_id = item.id
    await opensearch.refresh()
    yield token
    async with get_sessionmaker()() as session:
        await opensearch.delete_by_ids("memory", [str(item_id)], refresh=True)
        row = await session.get(MemoryItem, item_id)
        if row is not None:
            await session.delete(row)
            await session.commit()


async def _context_text(client: httpx.AsyncClient, space: Space, token: str) -> str:
    response = await client.post(
        f"{API}/{space.slug}/context", json={"task": f"charte {token} rotation trimestrielle des badges"}
    )
    assert response.status_code == 200, response.text
    # the served passages only (the context text also echoes the task, which carries the token)
    return str([(i["title"], i["excerpt"]) for i in response.json()["items"]])


async def test_enforce_organisation_memory_belongs_to_the_default_workspace(
    spaces: tuple[Space, Space],
    org_memory: str,
    monkeypatch: pytest.MonkeyPatch,
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    a, b = spaces
    token = org_memory
    set_mode(monkeypatch, "off")
    assert token in await _context_text(b.owner_client, b, token)  # historical: served in every project
    set_mode(monkeypatch, "enforce")
    assert token not in await _context_text(a.owner_client, a, token)  # no space but the default one reads it
    assert token not in await _context_text(b.owner_client, b, token)
    listing = await b.owner_client.get(f"{API}/{b.slug}/memory", params={"q": token})
    assert token not in listing.text
    # the default workspace's own projects keep reading it
    default_owner = await _user(settings.default_workspace_id)
    default_client = await client_for(default_owner)
    created = await default_client.post(API, json={"name": f"Projet défaut {unique('d')}"})
    assert created.status_code == 201, created.text
    default_space = Space(
        workspace_id=settings.default_workspace_id,
        owner=default_owner,
        admin=default_owner,
        owner_client=default_client,
        admin_client=default_client,
        project=created.json(),
        document_id="",
        agent_key="",
        agent_id=uuid.uuid4(),
    )
    assert token in await _context_text(default_client, default_space, token)


# --- enforce: members, users, sharing, webhooks ---------------------------------------------------------


async def test_enforce_members_and_users_of_another_workspace_are_unknown(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = spaces
    add = {"email": b.owner.email, "role": "viewer"}
    set_mode(monkeypatch, "enforce")
    refused = await a.owner_client.post(f"{API}/{a.slug}/members", json=add)
    unknown = await a.owner_client.post(
        f"{API}/{a.slug}/members", json={"email": f"{unique('nobody')}@example.com", "role": "viewer"}
    )
    assert refused.status_code == unknown.status_code == 404
    assert refused.json() == unknown.json()  # an account of another space looks like an unknown address
    listed = {u["email"] for u in (await a.admin_client.get("/api/v1/users")).json()}
    assert a.owner.email in listed and b.owner.email not in listed
    assert (
        await a.admin_client.patch(f"/api/v1/users/{b.owner.id}", json={"full_name": "X"})
    ).status_code == 404
    set_mode(monkeypatch, "off")
    assert b.owner.email in {u["email"] for u in (await a.admin_client.get("/api/v1/users")).json()}
    assert (await a.owner_client.post(f"{API}/{a.slug}/members", json=add)).status_code == 201


async def test_webhooks_inherit_the_workspace_and_their_payload_carries_both_ids(
    spaces: tuple[Space, Space],
    receiver: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _b = spaces
    hook = await _hook(a.owner_client, a.project)
    async with get_sessionmaker()() as session:
        from app.models.features_feed import Webhook

        row = await session.get(Webhook, uuid.UUID(hook["id"]))
        assert row is not None and row.workspace_id == a.workspace_id
    await _decision(a.owner_client, a.project)
    await _run_webhook_jobs()
    import json

    payloads = [json.loads(r.content) for r in receiver.requests]
    assert payloads, "no webhook delivered"
    for payload in payloads:
        assert payload["workspace_id"] == str(a.workspace_id)
        assert payload["orion_project_id"] == str(a.project_id)
        assert payload["project"]["id"] == str(a.project_id)  # historical keys untouched


# --- shadow / off: counters and no behaviour change ----------------------------------------------------------


async def test_off_and_shadow_never_change_an_answer(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, _b = spaces
    answers = {}
    for mode in ("off", "shadow", "enforce"):
        set_mode(monkeypatch, mode)
        detail = (await a.owner_client.get(f"{API}/{a.slug}")).json()
        search = (await a.owner_client.get(f"{API}/{a.slug}/search", params={"q": "badges"})).json()
        answers[mode] = (detail, [h["document_id"] for h in search])
    assert answers["off"] == answers["shadow"] == answers["enforce"]  # a single space: identical everywhere


def test_allows_is_a_pure_decision_per_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    one, two = uuid.uuid4(), uuid.uuid4()
    for mode, expected_mismatch in (("off", True), ("shadow", True), ("enforce", False)):
        set_mode(monkeypatch, mode)
        assert workspaces.allows(one, one, surface="unit") is True
        assert workspaces.allows(one, two, surface="unit") is expected_mismatch
    set_mode(monkeypatch, "off")
    assert workspaces.org_memory_visible(None) is True


async def test_shadow_counts_every_surface_without_changing_an_answer(
    spaces: tuple[Space, Space], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = spaces
    async with get_sessionmaker()() as session:
        session.add(ProjectMember(project_id=a.project_id, user_id=b.owner.id, role="viewer"))
        await session.commit()
    set_mode(monkeypatch, "off")
    off_projects = sorted(p["slug"] for p in (await b.owner_client.get(API)).json())
    off_users = sorted(u["email"] for u in (await a.admin_client.get("/api/v1/users")).json())

    set_mode(monkeypatch, "shadow")
    before = {s: violations("shadow", s) for s in ("project_list", "user_list", "member_add", "user")}
    assert sorted(p["slug"] for p in (await b.owner_client.get(API)).json()) == off_projects
    assert sorted(u["email"] for u in (await a.admin_client.get("/api/v1/users")).json()) == off_users
    add = await a.owner_client.post(
        f"{API}/{a.slug}/members", json={"email": b.admin.email, "role": "viewer"}
    )
    assert add.status_code == 201  # served as before
    patched = await a.admin_client.patch(f"/api/v1/users/{b.owner.id}", json={"full_name": b.owner.full_name})
    assert patched.status_code == 200
    assert (
        violations("shadow", "project_list") == before["project_list"] + 1
    )  # A's project, seen by B's owner
    assert violations("shadow", "user_list") > before["user_list"]
    assert violations("shadow", "member_add") == before["member_add"] + 1
    assert violations("shadow", "user") == before["user"] + 1
