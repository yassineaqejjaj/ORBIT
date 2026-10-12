"""Contradiction map: clusters of contradicting memory, ranked, and never revealing what the caller cannot see."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import MemoryStatus, RelationNodeType, RelationType
from app.memory.contradiction_map import MapEdge, MapItem, build_clusters
from app.models import Relation
from tests.conftest import UserInfo

JSON = dict[str, Any]
T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _item(
    id_: str, status: MemoryStatus, *, day: int = 1, confidence: float = 0.7, classification: int = 1
) -> MapItem:
    return MapItem(id_, f"Item {id_}", "decision", status, classification, confidence, T0.replace(day=day))


def test_two_validated_items_that_contradict_are_critical_and_the_most_recent_is_suggested():
    items = [_item("a", MemoryStatus.validated, day=1), _item("b", MemoryStatus.validated, day=9)]
    [cluster] = build_clusters(items, [MapEdge("a", "b", 0.9, "nli", "Deux dates différentes")])
    assert (
        cluster["severity"] == "critical"
        and cluster["suggested_keep"] == "b"
        and set(cluster["item_ids"]) == {"a", "b"}
    )


def test_a_proposal_against_a_validated_item_needs_review_and_a_weak_unvalidated_clash_is_minor():
    review = build_clusters(
        [_item("a", MemoryStatus.validated), _item("b", MemoryStatus.proposed)],
        [MapEdge("a", "b", 0.9, None, None)],
    )
    assert (
        review[0]["severity"] == "review" and review[0]["suggested_keep"] == "a"
    )  # validated beats proposed
    weak = build_clusters(
        [_item("c", MemoryStatus.validated), _item("d", MemoryStatus.obsolete)],
        [MapEdge("c", "d", 0.2, None, None)],
    )
    assert weak == []  # an obsolete item is already settled


def test_clusters_are_connected_components_most_severe_first_and_ignore_unknown_or_duplicate_edges():
    items = [_item(i, MemoryStatus.validated) for i in "abcde"] + [
        _item("f", MemoryStatus.proposed),
        _item("g", MemoryStatus.proposed),
    ]
    edges = [
        MapEdge("a", "b", 0.9, None, None),
        MapEdge("b", "c", 0.8, None, None),
        MapEdge("b", "a", 0.9, None, None),  # same pair as the first
        MapEdge(
            "f", "g", 0.3, None, None
        ),  # weak, proposed-only: needs review (a proposal is open), not minor
        MapEdge("a", "zzz", 0.9, None, None),  # unknown item
        MapEdge("d", "d", 1.0, None, None),  # self loop
    ]
    clusters = build_clusters(items, edges)
    assert [c["severity"] for c in clusters] == ["critical", "review"]
    assert set(clusters[0]["item_ids"]) == {"a", "b", "c"} and len(clusters[0]["edges"]) == 2
    assert set(clusters[1]["item_ids"]) == {"f", "g"}


def test_no_contradictions_means_no_clusters():
    assert build_clusters([_item("a", MemoryStatus.validated)], []) == []


# --- API ---------------------------------------------------------------------------------------------------


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/memory"


async def _create(client: httpx.AsyncClient, project: JSON, **overrides: Any) -> JSON:
    body: JSON = {"scope": "project", "kind": "decision", "title": "x", "content": "x", "status": "validated"}
    body.update(overrides)
    response = await client.post(_base(project), json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _contradict(db: AsyncSession, project: JSON, a: JSON, b: JSON, *, score: float = 0.85) -> None:
    db.add(
        Relation(
            project_id=uuid.UUID(project["id"]),
            src_type=RelationNodeType.memory,
            src_id=uuid.UUID(a["id"]),
            rel_type=RelationType.contradicts,
            dst_type=RelationNodeType.memory,
            dst_id=uuid.UUID(b["id"]),
            confidence=score,
            score=score,
            method="lexical",
            explanation="Les deux décisions donnent des horaires différents.",
        )
    )
    await db.commit()


async def test_the_map_lists_clusters_with_their_items_and_explanation(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    a = await _create(
        admin_client, project, title="Navette à 20 min", content="La navette part toutes les 20 minutes."
    )
    b = await _create(
        admin_client, project, title="Navette à 30 min", content="La navette part toutes les 30 minutes."
    )
    await _create(admin_client, project, title="Sans rapport", content="Autre sujet.")

    # ORBIT detects the contradiction itself when the second item is written: no relation is inserted by hand.
    body = (await admin_client.get(f"{_base(project)}/contradictions")).json()
    assert body["counts"] == {"critical": 1, "review": 0, "minor": 0}
    [cluster] = body["clusters"]
    assert {i["title"] for i in cluster["items"]} == {"Navette à 20 min", "Navette à 30 min"}
    assert "30" in cluster["edges"][0]["explanation"] and cluster["suggested_keep"] in {a["id"], b["id"]}
    assert all(len(i["excerpt"]) <= 280 for i in cluster["items"])


async def test_a_contradiction_with_something_the_caller_cannot_see_is_neither_shown_nor_counted(
    admin_client: httpx.AsyncClient,
    project: JSON,
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    public = await _create(admin_client, project, title="Budget public", content="Le budget est de 100 k€.")
    secret = await _create(
        admin_client, project, title="Budget secret", content="Le budget est de 900 k€.", classification=3
    )
    await _contradict(db_session, project, public, secret)

    reader = await make_user(clearance=1)
    added = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": reader.email, "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    low = await client_for(reader)
    hidden = (await low.get(f"{_base(project)}/contradictions")).json()
    assert hidden == {"clusters": [], "counts": {"critical": 0, "review": 0, "minor": 0}}
    assert "Budget secret" not in (await low.get(f"{_base(project)}/contradictions")).text

    seen = (await admin_client.get(f"{_base(project)}/contradictions")).json()
    assert seen["counts"]["critical"] == 1 and max(c["max_classification"] for c in seen["clusters"]) == 3
