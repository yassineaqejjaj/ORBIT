"""What the project knew on one date versus another: appeared, gone (and why), rewritten."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.as_of_diff import Known, Latest, diff_known, explain
from app.models import MemoryItem as MemoryItemRow

JSON = dict[str, Any]
NOW = datetime(2026, 10, 12, tzinfo=UTC)


def _k(title: str, *, lineage: uuid.UUID | None = None, version: int = 1, content: str = "x") -> Known:
    return Known(uuid.uuid4(), lineage or uuid.uuid4(), version, title, content)


def test_added_removed_and_rewritten_lineages_are_told_apart():
    kept = _k("Inchangé")
    same = _k("Réécrit")
    rewritten = Known(uuid.uuid4(), same.lineage_id, 2, "Réécrit", "nouveau texte")
    gone = _k("Disparu")
    new = _k("Nouveau")
    result = diff_known(
        [kept, same, gone],
        [Known(kept.id, kept.lineage_id, 1, "Inchangé", "x"), rewritten, new],
        {gone.lineage_id: Latest("obsolete", None, None)},
        NOW,
    )
    assert [k.title for k in result.added] == ["Nouveau"]
    assert [(r.before.title, r.why) for r in result.removed] == [("Disparu", "obsolete")]
    assert [(c.before.content, c.after.content) for c in result.changed] == [("x", "nouveau texte")]


def test_a_new_version_with_identical_words_is_not_reported_as_a_change():
    first = _k("Même texte", content="a")
    second = Known(uuid.uuid4(), first.lineage_id, 2, "Même texte", "a")
    assert diff_known([first], [second], {}, NOW).changed == []


def test_why_something_is_gone_is_taken_from_what_was_recorded():
    assert explain(Latest("superseded", None, uuid.uuid4()), NOW) == "replaced"
    assert explain(Latest("validated", None, uuid.uuid4()), NOW) == "replaced"
    assert explain(Latest("obsolete", None, None), NOW) == "obsolete"
    assert explain(Latest("forgotten", None, None), NOW) == "forgotten"
    assert explain(Latest("validated", NOW - timedelta(days=1), None), NOW) == "expired"
    assert explain(Latest("validated", NOW + timedelta(days=1), None), NOW) == "unknown"
    assert explain(None, NOW) == "unknown"


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/memory"


async def _create(client: httpx.AsyncClient, project: JSON, **overrides: Any) -> JSON:
    body: JSON = {"scope": "project", "kind": "decision", "title": "x", "content": "x", "status": "validated"}
    body.update(overrides)
    response = await client.post(_base(project), json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _backdate(db: AsyncSession, item: JSON, when: datetime) -> None:
    row = await db.get(MemoryItemRow, uuid.UUID(item["id"]))
    assert row is not None
    row.created_at = when
    await db.commit()


async def test_the_diff_shows_what_replaced_what_between_two_dates(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    old = await _create(
        admin_client,
        project,
        title="Application native",
        content="Décision : application native iOS et Android.",
        valid_from="2026-03-01T09:00:00Z",
    )
    await _backdate(db_session, old, datetime(2026, 3, 1, 9, tzinfo=UTC))
    new = await _create(
        admin_client,
        project,
        title="PWA plutôt que native",
        content="Décision : une PWA, pas d'application native.",
        valid_from="2026-09-01T09:00:00Z",
    )
    done = await admin_client.post(f"{_base(project)}/{old['id']}/supersede", json={"by_id": new["id"]})
    assert done.status_code == 200, done.text

    response = await admin_client.get(
        f"{_base(project)}/as-of-diff", params={"from": "2026-04-01T00:00:00Z", "to": "2099-01-01T00:00:00Z"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [i["title"] for i in body["added"]] == ["PWA plutôt que native"]
    assert [(r["item"]["title"], r["why"]) for r in body["removed"]] == [("Application native", "replaced")]
    assert body["removed"][0]["replaced_by"]["title"] == "PWA plutôt que native"
    assert body["counts"] == {"added": 1, "removed": 1, "changed": 0}


async def test_dates_must_be_in_order(admin_client: httpx.AsyncClient, project: JSON) -> None:
    response = await admin_client.get(
        f"{_base(project)}/as-of-diff", params={"from": "2026-10-01T00:00:00Z", "to": "2026-09-01T00:00:00Z"}
    )
    assert response.status_code == 422


async def test_what_the_caller_cannot_see_never_appears_as_added(
    admin_client: httpx.AsyncClient, project: JSON, make_user: Any, client_for: Any
) -> None:
    await _create(admin_client, project, title="Budget secret", content="900 k€", classification=3)
    reader = await make_user(clearance=1)
    added = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/members", json={"email": reader.email, "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    low = await client_for(reader)
    response = await low.get(f"{_base(project)}/as-of-diff", params={"from": "2020-01-01T00:00:00Z"})
    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {"added": 0, "removed": 0, "changed": 0}
    assert "Budget secret" not in response.text
    full = (
        await admin_client.get(f"{_base(project)}/as-of-diff", params={"from": "2020-01-01T00:00:00Z"})
    ).json()
    assert [i["title"] for i in full["added"]] == ["Budget secret"] and full["max_classification"] == 3
