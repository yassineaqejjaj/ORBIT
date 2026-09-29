"""Short-term sessions API (docs/API.md « Sessions »): Valkey buffer, TTL, consolidation on close."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

JSON = dict[str, Any]


def _base(project: JSON) -> str:
    return f"/api/v1/projects/{project['slug']}/sessions"


async def test_session_turns_ttl_and_close(admin_client: httpx.AsyncClient, project: JSON) -> None:
    base = _base(project)
    session_id = f"sess-{uuid.uuid4().hex[:8]}"
    ttl_hours = int(project["settings"]["short_term_ttl_hours"])

    turns = [
        ("user", "Rédige la user story du check-in par QR code pour le pilote de Lyon."),
        (
            "agent",
            "Je consulte les décisions en vigueur. Le check-in par QR code a été validé en sprint review.",
        ),
        ("agent", "La story doit respecter la contrainte RGAA AA et le délai de réservation de 30 secondes."),
    ]
    for index, (role, content) in enumerate(turns, start=1):
        response = await admin_client.post(
            f"{base}/{session_id}/turns", json={"role": role, "content": content}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["session_id"] == session_id and body["turns"] == index
        expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        expected = datetime.now(UTC) + timedelta(hours=ttl_hours)
        assert abs((expires_at - expected).total_seconds()) < 120

    listed = (await admin_client.get(base)).json()
    entry = next(s for s in listed if s["session_id"] == session_id)
    assert entry["turns"] == 3 and entry["expires_at"]

    detail = (await admin_client.get(f"{base}/{session_id}")).json()
    assert [t["role"] for t in detail["turns"]] == ["user", "agent", "agent"]
    assert detail["expires_at"]

    closed = await admin_client.post(f"{base}/{session_id}/close")
    assert closed.status_code == 200, closed.text
    summary = closed.json()["summary"]
    assert summary is not None
    assert summary["kind"] == "summary" and summary["scope"] == "project"
    assert "QR code" in summary["content"]
    assert summary["provenance_count"] == 1

    assert (await admin_client.get(f"{base}/{session_id}")).status_code == 404
    assert session_id not in {s["session_id"] for s in (await admin_client.get(base)).json()}
    assert (await admin_client.post(f"{base}/{session_id}/close")).status_code == 404


async def test_agent_turns_and_validation(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[[str], httpx.AsyncClient]
) -> None:
    created = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/agents",
        json={"name": "Agent dev", "kind": "engineering", "description": "Code", "clearance": 1},
    )
    assert created.status_code == 201, created.text
    agent = agent_client(created.json()["api_key"])
    session_id = f"agent-{uuid.uuid4().hex[:8]}"
    ok = await agent.post(
        f"{_base(project)}/{session_id}/turns",
        json={"role": "agent", "content": "Analyse du ticket en cours."},
    )
    assert ok.status_code == 200, ok.text
    detail = await agent.get(f"{_base(project)}/{session_id}")
    assert detail.status_code == 200 and detail.json()["turns"][0]["content"] == "Analyse du ticket en cours."

    bad_id = await agent.post(f"{_base(project)}/bad id!/turns", json={"role": "agent", "content": "x"})
    assert bad_id.status_code in {404, 422}
    bad_role = await agent.post(
        f"{_base(project)}/{session_id}/turns", json={"role": "robot", "content": "x"}
    )
    assert bad_role.status_code == 422

    closed = await agent.post(f"{_base(project)}/{session_id}/close")
    assert closed.status_code == 200
    summary = closed.json()["summary"]
    assert summary is not None and summary["status"] == "proposed"
    assert summary["created_by_type"] == "agent"
