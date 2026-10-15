"""NOV-97: forgetting also rewrites persisted contexts and snapshots at rest (direct database reads).

Fictitious data only; no network (hash embeddings)."""

from __future__ import annotations

import argparse
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.__main__ import run_purge_forgotten
from app.context.snapshots import content_hash
from app.models import ContextDecision, ContextRequest, ContextSnapshot
from tests.test_api_documents import _text, drain

API = "/api/v1/projects"
JSON = dict[str, Any]
MEMORY_SECRET = "le coffre-fort du hall zéphyr contient quarante badges dorés"
DOCUMENT_SECRET = "la salle quartz du hall zéphyr accueille trente exposants invités"
KEPT = "le plan du hall zéphyr prévoit douze bornes de recharge"
TASK = "hall zéphyr coffre-fort salle quartz bornes badges exposants"


async def _serve(client: httpx.AsyncClient, slug: str, snapshot: str) -> JSON:
    response = await client.post(
        f"{API}/{slug}/context",
        json={"task": TASK, "min_relevance": 0, "save_snapshot": {"name": snapshot}},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _rows(session: AsyncSession, slug_project_id: uuid.UUID) -> tuple[str, str, list[ContextSnapshot]]:
    """Everything persisted about served contexts, as one text each (a direct read of the tables)."""
    session.expire_all()
    decisions = " ".join(
        (
            await session.scalars(
                select(ContextDecision.excerpt)
                .join(ContextRequest)
                .where(ContextRequest.project_id == slug_project_id)
            )
        ).all()
    )
    requests = " ".join(
        (
            await session.scalars(
                select(ContextRequest.context_text).where(ContextRequest.project_id == slug_project_id)
            )
        ).all()
    )
    snapshots = list(
        (
            await session.scalars(
                select(ContextSnapshot).where(ContextSnapshot.project_id == slug_project_id)
            )
        ).all()
    )
    return decisions, requests, snapshots


def _snapshot_text(snapshots: list[ContextSnapshot]) -> str:
    return " ".join(
        s.content + " " + " ".join(i.get("excerpt", "") + i.get("title", "") for i in s.items)
        for s in snapshots
    )


async def _setup(admin_client: httpx.AsyncClient, project: JSON) -> tuple[str, JSON, JSON]:
    slug = str(project["slug"])
    memory = await admin_client.post(
        f"{API}/{slug}/memory",
        json={
            "scope": "project",
            "kind": "decision",
            "status": "validated",
            "title": "Coffre-fort du hall",
            "content": f"Décision : {MEMORY_SECRET}.",
        },
    )
    assert memory.status_code == 201, memory.text
    document = await _text(
        admin_client, slug, title="Salle quartz", content=f"{DOCUMENT_SECRET.capitalize()}."
    )
    await _text(admin_client, slug, title="Plan du hall", content=f"{KEPT.capitalize()}.")
    await drain()
    return slug, memory.json(), document


async def test_forgetting_a_memory_rewrites_decisions_requests_and_snapshots(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    slug, memory, _document = await _setup(admin_client, project)
    project_id = uuid.UUID(str(project["id"]))
    served = await _serve(admin_client, slug, "hall-zephyr")
    assert any(MEMORY_SECRET in i["excerpt"] for i in served["items"]), "the decision is served"
    decisions, requests, snapshots = await _rows(db_session, project_id)
    assert (
        MEMORY_SECRET in decisions
        and MEMORY_SECRET in requests
        and MEMORY_SECRET in _snapshot_text(snapshots)
    )

    forgot = await admin_client.post(f"{API}/{slug}/memory/{memory['id']}/forget", json={"reason": "RGPD"})
    assert forgot.status_code == 200, forgot.text

    decisions, requests, snapshots = await _rows(db_session, project_id)
    assert MEMORY_SECRET not in decisions and MEMORY_SECRET not in requests
    assert MEMORY_SECRET not in _snapshot_text(snapshots)
    assert "[oublié]" in requests and "[oublié]" in decisions
    for snapshot in snapshots:  # the hash follows the rewritten content
        assert snapshot.content_hash == content_hash(snapshot.content)
        flagged = [i for i in snapshot.items if i["key"].startswith("memory:") and i.get("forgotten")]
        assert flagged and all(i["excerpt"] == "[oublié]" for i in flagged)
    assert KEPT in requests.lower()  # what was not forgotten is untouched
    # The audit trail says how much was rewritten.
    audit = await admin_client.get(f"{API}/{slug}/audit", params={"action": "memory.forget"})
    assert audit.json()["items"][0]["details"]["purged_context"]["decisions"] >= 1


async def test_forgetting_a_document_rewrites_its_chunks_everywhere(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession
) -> None:
    slug, _memory, document = await _setup(admin_client, project)
    project_id = uuid.UUID(str(project["id"]))
    served = await _serve(admin_client, slug, "hall-zephyr")
    assert any(DOCUMENT_SECRET in i["excerpt"].lower() for i in served["items"]), "the chunk is served"
    decisions, requests, snapshots = await _rows(db_session, project_id)
    assert DOCUMENT_SECRET in decisions.lower() and DOCUMENT_SECRET in requests.lower()

    forgot = await admin_client.post(
        f"{API}/{slug}/documents/{document['id']}/forget", json={"reason": "RGPD"}
    )
    assert forgot.status_code == 200, forgot.text
    await drain()

    decisions, requests, snapshots = await _rows(db_session, project_id)
    for text in (decisions, requests, _snapshot_text(snapshots)):
        assert DOCUMENT_SECRET not in text.lower()
    assert KEPT in requests.lower() or KEPT in decisions.lower()
    for snapshot in snapshots:
        assert snapshot.content_hash == content_hash(snapshot.content)


async def test_catch_up_command_is_idempotent_and_supports_dry_run(
    admin_client: httpx.AsyncClient, project: JSON, db_session: AsyncSession, capsys: Any
) -> None:
    slug, memory, _document = await _setup(admin_client, project)
    project_id = uuid.UUID(str(project["id"]))
    await _serve(admin_client, slug, "hall-zephyr")
    await admin_client.post(f"{API}/{slug}/memory/{memory['id']}/forget", json={"reason": "RGPD"})

    # Put the text back as a restored backup would: forgotten in the live tables, quoted in the copies.
    rows = (
        await db_session.scalars(
            select(ContextDecision).join(ContextRequest).where(ContextRequest.project_id == project_id)
        )
    ).all()
    quoted = [d for d in rows if d.excerpt == "[oublié]"]
    assert quoted
    for decision in quoted:
        decision.excerpt = MEMORY_SECRET
    for snapshot in (
        await db_session.scalars(select(ContextSnapshot).where(ContextSnapshot.project_id == project_id))
    ).all():
        snapshot.items = [
            {**i, "excerpt": MEMORY_SECRET, "forgotten": False} if i["key"].startswith("memory:") else i
            for i in snapshot.items
        ]
    await db_session.commit()

    def args(*, dry_run: bool = False) -> argparse.Namespace:
        return argparse.Namespace(project=slug, dry_run=dry_run, json=True)

    assert await run_purge_forgotten(args(dry_run=True)) == 0
    dry = capsys.readouterr().out
    assert '"dry_run": true' in dry and '"decisions": 0' not in dry
    decisions, _requests, snapshots = await _rows(db_session, project_id)
    assert MEMORY_SECRET in decisions  # a dry run writes nothing

    assert await run_purge_forgotten(args()) == 0
    capsys.readouterr()
    decisions, _requests, snapshots = await _rows(db_session, project_id)
    assert MEMORY_SECRET not in decisions and MEMORY_SECRET not in _snapshot_text(snapshots)

    assert await run_purge_forgotten(args()) == 0  # second run: nothing left to do
    again = capsys.readouterr().out
    assert '"decisions": 0' in again and '"snapshots": 0' in again
    audit = await admin_client.get(f"{API}/{slug}/audit", params={"action": "governance.forget_purge"})
    assert len(audit.json()["items"]) == 1  # only the run that rewrote something is logged
