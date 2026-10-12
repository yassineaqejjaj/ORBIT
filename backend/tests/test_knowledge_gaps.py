"""Knowledge gaps: recurring missing topics, reduced to topics, for editors; one click opens the documentation task."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.knowledge_gaps import MissingTopic, aggregate, severity, topic_key, trend
from app.enums import PrincipalKind
from app.models import ContextRequest
from tests.conftest import UserInfo

JSON = dict[str, Any]
NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


def _m(topic: str, days_ago: float, asker: str = "u1", score: float = 0.2) -> MissingTopic:
    return MissingTopic(topic, NOW - timedelta(days=days_ago), asker, score)


def test_the_same_topic_in_different_words_is_one_gap():
    assert topic_key("rétention des données") == topic_key("des données, rétention")
    gaps = aggregate(
        [
            _m("durée de rétention des données", 1),
            _m("rétention des données", 2, "u2"),
            _m("budget de la phase 2", 3),
        ],
        NOW,
        30,
    )
    assert [g["requests"] for g in gaps] == [2, 1]
    assert gaps[0]["askers"] == 2 and gaps[0]["topic"] in {
        "durée de rétention des données",
        "rétention des données",
    }


def test_severity_follows_frequency_and_the_number_of_different_askers():
    assert severity(1, 1) == "isolated" and severity(2, 1) == "recurring"
    assert severity(5, 1) == "critical" and severity(2, 3) == "critical"


def test_the_trend_needs_a_clear_difference_between_the_two_halves_of_the_window():
    recent = [NOW - timedelta(days=d) for d in (1, 2, 3, 4)]
    old = [NOW - timedelta(days=d) for d in (25, 26)]
    assert trend(recent + old[:1], NOW, 30) == "rising"
    assert trend(old + recent[:1], NOW, 30) == "fading"
    assert trend([NOW - timedelta(days=1), NOW - timedelta(days=28)], NOW, 30) == "steady"


def test_topics_sharing_a_single_word_stay_apart():
    gaps = aggregate([_m("budget de la phase 2", 1), _m("budget du marketing", 1), _m("budget", 1)], NOW, 30)
    assert len(gaps) == 3  # « budget » alone is not enough to say two topics are the same


def test_topics_with_nothing_to_key_on_are_ignored():
    assert aggregate([_m("???", 1), _m("le la les", 1)], NOW, 30) == []


# --- API ---------------------------------------------------------------------------------------------------


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/knowledge-gaps"


async def _ask(
    db: AsyncSession, project: JSON, task: str, missing: list[str], verdict: str = "insufficient"
) -> None:
    db.add(
        ContextRequest(
            project_id=uuid.UUID(project["id"]),
            trace_id=uuid.uuid4().hex,
            task=task,
            requested_by_type=PrincipalKind.user,
            params={"sufficiency": {"verdict": verdict, "score": 0.1, "missing_subtopics": missing}},
        )
    )
    await db.commit()


async def test_gaps_are_aggregated_without_exposing_the_questions(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    secret_task = "Que décide-t-on pour le contrat confidentiel de Dupont ?"
    for _ in range(3):
        await _ask(db_session, project, secret_task, ["politique de rétention des données"])
    await _ask(db_session, project, "autre question", ["budget de la phase 2"], verdict="partial")
    await _ask(db_session, project, "question couverte", ["sujet couvert"], verdict="sufficient")

    response = await admin_client.get(_base(project))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysed_requests"] == 5
    topics = {g["topic"]: g for g in body["gaps"]}
    assert set(topics) == {"politique de rétention des données", "budget de la phase 2"}
    assert topics["politique de rétention des données"]["requests"] == 3
    assert topics["politique de rétention des données"]["severity"] == "recurring"
    assert (
        "Dupont" not in response.text and "contrat confidentiel" not in response.text
    )  # topics only, never the question


async def test_only_editors_can_read_the_gaps(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    viewer = await make_user(clearance=1)
    added = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": viewer.email, "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    reader = await client_for(viewer)
    assert (await reader.get(_base(project))).status_code == 403
    assert (
        await reader.post(f"{_base(project)}/request", json={"topic": "politique de rétention"})
    ).status_code == 403


async def test_requesting_documentation_opens_one_proposed_action_and_marks_the_gap(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    await _ask(db_session, project, "q", ["politique de rétention des données"])
    first = await admin_client.post(
        f"{_base(project)}/request", json={"topic": "politique de rétention des données"}
    )
    assert first.status_code == 201, first.text
    item = first.json()
    assert item["kind"] == "action" and item["status"] == "proposed" and "knowledge-gap" in item["tags"]
    assert item["title"] == "Documenter : politique de rétention des données"

    again = await admin_client.post(
        f"{_base(project)}/request", json={"topic": "politique de rétention des données"}
    )
    assert again.status_code == 409
    gaps = (await admin_client.get(_base(project))).json()["gaps"]
    assert gaps[0]["requested"] is True
    assert (await admin_client.post(f"{_base(project)}/request", json={"topic": "???"})).status_code in (
        409,
        422,
    )


async def test_contributors_are_the_authors_of_related_memory_not_the_requester(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    await _ask(db_session, project, "q", ["politique de rétention des données"])
    created = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/memory",
        json={
            "scope": "project",
            "kind": "decision",
            "title": "Rétention des données clients",
            "content": "Décision : trois ans après la fin du contrat.",
            "status": "validated",
        },
    )
    assert created.status_code == 201, created.text

    before = (await admin_client.get(_base(project))).json()["gaps"][0]
    assert [c["items"] for c in before["contributors"]] == [1]  # the author of the related decision

    await admin_client.post(f"{_base(project)}/request", json={"topic": "politique de rétention des données"})
    after = (await admin_client.get(_base(project))).json()["gaps"][0]
    assert [c["items"] for c in after["contributors"]] == [1]  # the new « Documenter » action did not count
