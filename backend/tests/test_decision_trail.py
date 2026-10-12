"""Decision trail: the recorded story behind a decision, limited to what the caller may see."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.decision_trail import TrailEntry, build_timeline, excerpt
from app.models import MemoryItem as MemoryItemRow
from tests.conftest import UserInfo

JSON = dict[str, Any]


def _at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=UTC)


def test_the_timeline_is_chronological_reads_source_before_creation_and_lists_duplicates_once():
    entries = [
        TrailEntry(_at(2), "validated", "Validé — A", item_id="a"),
        TrailEntry(_at(1), "created", "Créé — A", item_id="a"),
        TrailEntry(_at(1), "source", "Compte rendu du 1er", item_id="a"),
        TrailEntry(_at(2), "validated", "Validé — A", item_id="a"),  # same instant, kind, label and item
        TrailEntry(_at(5), "replaced_by", "« A » remplacé par « B »", item_id="b"),
    ]
    timeline = build_timeline(entries)
    assert [e.kind for e in timeline] == ["source", "created", "validated", "replaced_by"]


def test_an_excerpt_collapses_whitespace_and_stays_short():
    assert excerpt("a  b\n c") == "a b c"
    assert len(excerpt("mot " * 400)) <= 300 and excerpt("mot " * 400).endswith("…")


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/memory"


async def _create(client: httpx.AsyncClient, project: JSON, **overrides: Any) -> JSON:
    body: JSON = {"scope": "project", "kind": "decision", "title": "x", "content": "x", "status": "validated"}
    body.update(overrides)
    response = await client.post(_base(project), json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _chain(
    client: httpx.AsyncClient, db: AsyncSession, project: JSON, *, old_classification: int = 1
) -> tuple[JSON, JSON]:
    old = await _create(
        client,
        project,
        title="Login email et mot de passe",
        content="Décision : connexion par email et mot de passe.",
        valid_from="2026-06-01T09:00:00Z",
        classification=old_classification,
    )
    new = await _create(
        client,
        project,
        title="Authentification SSO OIDC",
        content="Décision : authentification SSO OIDC (Keycloak).",
        valid_from="2026-09-01T09:00:00Z",
    )
    # Rationale and decider are recorded by extraction, not accepted from the create API.
    row = await db.get(MemoryItemRow, uuid.UUID(new["id"]))
    assert row is not None
    row.rationale, row.decided_by = "Exigence du client : un seul compte d'entreprise.", "Comité produit"
    await db.commit()
    done = await client.post(
        f"{_base(project)}/{old['id']}/supersede", json={"by_id": new["id"], "reason": "Décision du comité"}
    )
    assert done.status_code == 200, done.text
    return old, new


async def test_the_trail_orders_what_was_replaced_and_explains_why(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    old, new = await _chain(admin_client, db_session, project)
    body = (await admin_client.get(f"{_base(project)}/{new['id']}/trail")).json()

    assert [(c["id"], c["role"]) for c in body["chain"]] == [(old["id"], "replaced"), (new["id"], "current")]
    assert (
        body["why"]["rationale"].startswith("Exigence du client")
        and body["why"]["decided_by"] == "Comité produit"
    )
    kinds = [e["kind"] for e in body["timeline"]]
    assert "replaced_by" in kinds and "created" in kinds and "superseded" in kinds
    replaced = next(e for e in body["timeline"] if e["kind"] == "replaced_by")
    assert (
        "Login email et mot de passe" in replaced["label"]
        and "Authentification SSO OIDC" in replaced["label"]
    )
    times = [e["at"] for e in body["timeline"]]
    assert times == sorted(times)

    from_old = (await admin_client.get(f"{_base(project)}/{old['id']}/trail")).json()
    assert from_old["item_id"] in {
        old["id"],
        new["id"],
    }  # the trail of the oldest version leads to the same story
    assert {c["id"] for c in from_old["chain"]} == {old["id"], new["id"]}


async def test_a_replaced_item_the_caller_cannot_see_is_left_out_of_the_trail(
    admin_client: httpx.AsyncClient,
    project: JSON,
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    old, new = await _chain(admin_client, db_session, project, old_classification=3)
    reader = await make_user(clearance=1)
    added = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": reader.email, "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    low = await client_for(reader)

    response = await low.get(f"{_base(project)}/{new['id']}/trail")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["id"] for c in body["chain"]] == [new["id"]]
    assert "Login email et mot de passe" not in response.text and body["max_classification"] == 1
    assert (
        await low.get(f"{_base(project)}/{old['id']}/trail")
    ).status_code == 404  # its existence is not revealed

    full = (await admin_client.get(f"{_base(project)}/{new['id']}/trail")).json()
    assert [c["id"] for c in full["chain"]] == [old["id"], new["id"]] and full["max_classification"] == 3
