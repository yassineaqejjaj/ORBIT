"""F1 — memory triage inbox & conflict arbitration (docs/FEATURES.md)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import UserInfo

JSON = dict[str, Any]


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}"


async def _create(client: httpx.AsyncClient, project: JSON, **overrides: Any) -> JSON:
    body: JSON = {
        "scope": "project",
        "kind": "fact",
        "title": f"Fait {uuid.uuid4().hex[:6]}",
        "content": f"Le service de navette fonctionne de {uuid.uuid4().hex[:8]} heures.",
        "status": "proposed",
    }
    body.update(overrides)
    response = await client.post(f"{_base(project)}/memory", json=body)
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
    added = await admin_client.post(f"{_base(project)}/members", json={"email": user.email, "role": role})
    assert added.status_code == 201, added.text
    return user, await client_for(user)


async def _contradiction(db_session: AsyncSession, project: JSON, a: JSON, b: JSON) -> uuid.UUID:
    from app.enums import RelationNodeType, RelationType
    from app.models import Relation

    existing = await db_session.scalar(
        select(Relation).where(
            Relation.rel_type == RelationType.contradicts,
            Relation.src_id.in_([uuid.UUID(a["id"]), uuid.UUID(b["id"])]),
            Relation.dst_id.in_([uuid.UUID(a["id"]), uuid.UUID(b["id"])]),
        )
    )
    if existing is not None:
        return existing.id
    relation = Relation(
        project_id=uuid.UUID(project["id"]),
        src_type=RelationNodeType.memory,
        src_id=uuid.UUID(a["id"]),
        rel_type=RelationType.contradicts,
        dst_type=RelationNodeType.memory,
        dst_id=uuid.UUID(b["id"]),
        confidence=0.82,
        detail="Similarité 82 % · valeurs divergentes",
    )
    db_session.add(relation)
    await db_session.commit()
    return relation.id


async def test_inbox_lists_visible_proposals_with_signals(
    admin_client: httpx.AsyncClient,
    project: JSON,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    proposal = await _create(
        admin_client,
        project,
        title="Navette",
        content="La navette du salon part toutes les 20 minutes du hall A.",
    )
    await _create(
        admin_client,
        project,
        title="Navette (doublon)",
        content="La navette du salon part toutes les 20 minutes du hall A le matin.",
        status="validated",
    )
    secret = await _create(admin_client, project, title="Secret", classification=3)
    private = await _create(admin_client, project, scope="user", title="Préférence privée", kind="preference")

    listing = await admin_client.get(f"{base}/inbox", params={"sort": "recent"})
    assert listing.status_code == 200, listing.text
    ids = {item["id"] for item in listing.json()["items"]}
    assert proposal["id"] in ids
    assert all(item["status"] == "proposed" for item in listing.json()["items"])
    entry = next(item for item in listing.json()["items"] if item["id"] == proposal["id"])
    assert entry["impact"] == 0 and entry["would_be_included"] == 0
    assert entry["similar"] is not None and entry["similar"]["title"] == "Navette (doublon)"
    assert 0 < entry["similar"]["score"] <= 1

    for sort in ("impact", "confidence"):
        assert (await admin_client.get(f"{base}/inbox", params={"sort": sort})).status_code == 200
    filtered = await admin_client.get(f"{base}/inbox", params={"kind": "decision"})
    assert proposal["id"] not in {i["id"] for i in filtered.json()["items"]}
    high = await admin_client.get(f"{base}/inbox", params={"min_confidence": 0.99})
    assert proposal["id"] not in {i["id"] for i in high.json()["items"]}

    _, editor = await _member(admin_client, project, make_user, client_for, "editor", clearance=1)
    editor_ids = {
        i["id"] for i in (await editor.get(f"{base}/inbox", params={"page_size": 100})).json()["items"]
    }
    assert proposal["id"] in editor_ids
    assert secret["id"] not in editor_ids  # clearance
    assert private["id"] not in editor_ids  # user memory stays private to its subject

    count = await editor.get(f"{base}/inbox/count")
    assert count.status_code == 200 and count.json()["proposals"] >= 1

    _, viewer = await _member(admin_client, project, make_user, client_for, "viewer")
    denied = await viewer.get(f"{base}/inbox")
    assert denied.status_code == 403 and denied.json()["code"] == "forbidden"


async def test_bulk_validate_reject_merge(admin_client: httpx.AsyncClient, project: JSON) -> None:
    base = _base(project)
    a = await _create(admin_client, project)
    b = await _create(admin_client, project)
    validated = await _create(admin_client, project, status="validated")

    result = await admin_client.post(
        f"{base}/inbox/bulk",
        json={"action": "validate", "ids": [a["id"], validated["id"], str(uuid.uuid4())]},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["processed"] == 1
    failed = {f["id"]: f["detail"] for f in body["failed"]}
    assert failed[validated["id"]] == "Cet item est déjà validé"
    assert len(failed) == 2
    assert (await admin_client.get(f"{base}/memory/{a['id']}")).json()["item"]["status"] == "validated"

    rejected = await admin_client.post(
        f"{base}/inbox/bulk", json={"action": "reject", "ids": [b["id"]], "reason": "hors sujet"}
    )
    assert rejected.json() == {"processed": 1, "failed": []}
    detail = (await admin_client.get(f"{base}/memory/{b['id']}")).json()
    assert detail["item"]["status"] == "obsolete"
    assert any((e.get("reason") or "").startswith("Rejeté au tri") for e in detail["history"])

    # Merge: provenance copied into the target, the others become obsolete.
    target = await _create(
        admin_client, project, provenance=[{"source_label": "Atelier 1", "excerpt": "extrait A"}]
    )
    other = await _create(
        admin_client, project, provenance=[{"source_label": "Atelier 2", "excerpt": "extrait B"}]
    )
    missing_into = await admin_client.post(
        f"{base}/inbox/bulk", json={"action": "merge", "ids": [other["id"]]}
    )
    assert missing_into.status_code == 422
    merged = await admin_client.post(
        f"{base}/inbox/bulk",
        json={"action": "merge", "ids": [other["id"], target["id"]], "into_id": target["id"]},
    )
    assert merged.json() == {"processed": 1, "failed": []}
    target_detail = (await admin_client.get(f"{base}/memory/{target['id']}")).json()
    assert {p["excerpt"] for p in target_detail["provenance"]} >= {"extrait A", "extrait B"}
    other_detail = (await admin_client.get(f"{base}/memory/{other['id']}")).json()
    assert other_detail["item"]["status"] == "obsolete"
    assert any("Fusionné dans" in (e.get("reason") or "") for e in other_detail["history"])

    audit = await admin_client.get(f"{base}/audit", params={"action": "memory.bulk"})
    assert audit.status_code == 200
    assert len(audit.json()["items"]) == 3


async def test_conflict_resolution_and_dismissal(
    admin_client: httpx.AsyncClient,
    project: JSON,
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    a = await _create(
        admin_client,
        project,
        title="Budget 720",
        content="Le budget de l'événement est de 720 k€.",
        status="validated",
    )
    b = await _create(
        admin_client, project, title="Budget 650", content="Le budget de l'événement est de 650 k€."
    )
    conflict_id = await _contradiction(db_session, project, a, b)

    open_ = await admin_client.get(f"{base}/conflicts")
    assert open_.status_code == 200, open_.text
    entry = next(c for c in open_.json() if c["id"] == str(conflict_id))
    assert entry["status"] == "open"
    assert {entry["a"]["id"], entry["b"]["id"]} == {a["id"], b["id"]}
    assert entry["suggested_winner_id"] == a["id"]  # validated > proposed
    assert "validé" in entry["rationale"]
    assert "sources" in entry["a"]
    count = (await admin_client.get(f"{base}/inbox/count")).json()
    assert count["conflicts"] >= 1

    _, viewer = await _member(admin_client, project, make_user, client_for, "viewer")
    assert (await viewer.get(f"{base}/conflicts")).status_code == 200
    forbidden = await viewer.post(f"{base}/conflicts/{conflict_id}/resolve", json={"winner_id": a["id"]})
    assert forbidden.status_code == 403

    bad = await admin_client.post(
        f"{base}/conflicts/{conflict_id}/resolve", json={"winner_id": str(uuid.uuid4())}
    )
    assert bad.status_code == 422

    resolved = await admin_client.post(
        f"{base}/conflicts/{conflict_id}/resolve", json={"winner_id": a["id"], "reason": "Chiffre du comité"}
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution"]["winner_id"] == a["id"]
    loser = (await admin_client.get(f"{base}/memory/{b['id']}")).json()["item"]
    assert loser["status"] == "superseded" and loser["superseded_by_id"] == a["id"]
    assert str(conflict_id) not in {c["id"] for c in (await admin_client.get(f"{base}/conflicts")).json()}
    history = (await admin_client.get(f"{base}/conflicts", params={"status": "resolved"})).json()
    assert str(conflict_id) in {c["id"] for c in history}
    again = await admin_client.post(f"{base}/conflicts/{conflict_id}/resolve", json={"winner_id": a["id"]})
    assert again.status_code == 409
    audit = await admin_client.get(f"{base}/audit", params={"action": "memory.conflict_resolved"})
    assert audit.json()["items"]

    # Dismissal: the relation no longer counts as a contradiction.
    c = await _create(admin_client, project, title="Salle A", content="La salle A accueille 300 personnes.")
    d = await _create(
        admin_client, project, title="Salle A bis", content="La salle A accueille 120 personnes."
    )
    second = await _contradiction(db_session, project, c, d)
    dismissed = await admin_client.post(
        f"{base}/conflicts/{second}/dismiss", json={"reason": "Configurations"}
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"
    assert str(second) not in {x["id"] for x in (await admin_client.get(f"{base}/conflicts")).json()}
    for item in (c, d):
        status = (await admin_client.get(f"{base}/memory/{item['id']}")).json()["item"]["status"]
        assert status == "proposed"
    missing = await admin_client.post(f"{base}/conflicts/{uuid.uuid4()}/dismiss", json={})
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"


async def test_conflict_hidden_when_one_side_is_not_visible(
    admin_client: httpx.AsyncClient,
    project: JSON,
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[UserInfo]],
    client_for: Callable[[UserInfo], Awaitable[httpx.AsyncClient]],
) -> None:
    base = _base(project)
    a = await _create(admin_client, project, content="Le stand mesure 40 m².")
    b = await _create(admin_client, project, content="Le stand mesure 60 m².", classification=3)
    conflict_id = await _contradiction(db_session, project, a, b)
    _, editor = await _member(admin_client, project, make_user, client_for, "editor", clearance=1)
    assert str(conflict_id) not in {c["id"] for c in (await editor.get(f"{base}/conflicts")).json()}
    hidden = await editor.post(f"{base}/conflicts/{conflict_id}/dismiss", json={})
    assert hidden.status_code == 404


async def test_demo_capacity_pair_is_detected_as_conflict(
    admin_client: httpx.AsyncClient, project: JSON
) -> None:
    """The pair added to the demo seed (open conflict on the overview / inbox) is detected naturally."""
    base = _base(project)
    a = await _create(
        admin_client,
        project,
        kind="constraint",
        status="validated",
        title="Capacité du plateau de Lille",
        content="Le plateau de Lille compte 180 postes réservables dans Atlas.",
    )
    b = await _create(
        admin_client,
        project,
        kind="constraint",
        title="Capacité du plateau de Lille (mise à jour)",
        content="Le plateau de Lille compte 150 postes réservables dans Atlas.",
    )
    conflicts = (await admin_client.get(f"{base}/conflicts")).json()
    assert any({c["a"]["id"], c["b"]["id"]} == {a["id"], b["id"]} for c in conflicts)
    events = (await admin_client.get(f"{base}/changes", params={"types": "memory.conflict_detected"})).json()
    assert events["total"] >= 1
