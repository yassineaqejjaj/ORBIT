"""ORION validated learnings: submission with evidence, governance, scope of application."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.context.assembler import _apply_procedure_scope
from app.enums import MemoryKind, ReasonCode
from app.memory import learnings

JSON = dict[str, Any]


def _body(**over: Any) -> JSON:
    body: JSON = {
        "title": "Citer la règle métier avant de répondre",
        "content": "Quand une règle de remboursement est servie, la citer mot pour mot dans la réponse.",
        "applies_to": {"task_types": ["specification"], "agent_kinds": ["product"], "skills": ["prd"]},
        "evidence": {
            "experiment_id": "exp-42",
            "eval_suite_id": "suite-7",
            "run_ids": ["r1", "r2", "r3"],
            "runs": 12,
            "metric": "pass_rate",
            "baseline": 0.58,
            "candidate": 0.75,
        },
    }
    body.update(over)
    return body


async def _forge(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[..., httpx.AsyncClient]
) -> httpx.AsyncClient:
    created = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/agents",
        json={"name": "FORGE", "kind": "engineering", "description": "Évaluation", "clearance": 1},
    )
    assert created.status_code == 201, created.text
    return agent_client(created.json()["api_key"])


@pytest.mark.asyncio
async def test_forge_submits_a_learning_that_waits_for_validation(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[..., httpx.AsyncClient]
) -> None:
    forge = await _forge(admin_client, project, agent_client)
    url = f"/api/v1/projects/{project['slug']}/learnings"
    response = await forge.post(url, json=_body())
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["kind"] == "learning" and item["status"] == "proposed" and item["created_by_label"] == "FORGE"
    meta = item["learning_meta"]
    assert meta["evidence"]["delta"] == 0.17 and meta["evidence"]["experiment_id"] == "exp-42"
    assert meta["applies_to"] == {
        "task_types": ["specification"],
        "agent_kinds": ["product"],
        "skills": ["prd"],
        "tools": [],
        "agent_versions": [],
    }
    assert item["provenance_count"] == 1

    listed = await forge.get(url)
    assert listed.status_code == 200 and [i["id"] for i in listed.json()["items"]] == [item["id"]]
    assert (await forge.get(url, params={"status": "validated"})).json()["items"] == []

    # A human validates it; a new version (edit) keeps its scope and evidence.
    validated = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/memory/{item['id']}/validate", json={}
    )
    assert validated.status_code == 200, validated.text
    edited = await admin_client.patch(
        f"/api/v1/projects/{project['slug']}/memory/{item['id']}", json={"title": "Citer la règle (v2)"}
    )
    assert edited.status_code == 200 and edited.json()["learning_meta"] == meta


@pytest.mark.asyncio
async def test_evidence_must_be_a_real_improvement_on_enough_runs(
    admin_client: httpx.AsyncClient, project: JSON, agent_client: Callable[..., httpx.AsyncClient]
) -> None:
    forge = await _forge(admin_client, project, agent_client)
    url = f"/api/v1/projects/{project['slug']}/learnings"
    few = _body()
    few["evidence"] = {**few["evidence"], "runs": 2}
    assert (await forge.post(url, json=few)).status_code == 422
    flat = _body()
    flat["evidence"] = {**flat["evidence"], "candidate": 0.58}
    assert (await forge.post(url, json=flat)).status_code == 422
    unknown = _body(applies_to={"task_types": ["nope"]})
    assert (await forge.post(url, json=unknown)).status_code == 422
    assert (
        await forge.post(url, json={**_body(), "status": "validated"})
    ).status_code == 422  # no self-validation


@pytest.mark.asyncio
async def test_a_learning_cannot_be_created_without_evidence_through_the_memory_api(
    admin_client: httpx.AsyncClient, project: JSON
) -> None:
    response = await admin_client.post(
        f"/api/v1/projects/{project['slug']}/memory",
        json={"scope": "project", "kind": "learning", "title": "Sans preuve", "content": "Aucune preuve."},
    )
    assert response.status_code == 422


def test_scope_of_application() -> None:
    meta = learnings.normalize_meta(
        {"task_types": ["specification"], "agent_kinds": ["product"]},
        {"runs": 5, "metric": "m", "baseline": 0.1, "candidate": 0.4},
    )
    assert learnings.applies_to(meta, "specification", "product") == (True, "")
    assert learnings.applies_to(meta, "design", "product")[0] is False
    assert learnings.applies_to(meta, "specification", "design")[0] is False
    assert learnings.applies_to(meta, None, None) == (True, "")  # unknown request: served
    everywhere = learnings.normalize_meta({}, {"runs": 5, "metric": "m", "baseline": 0.1, "candidate": 0.4})
    assert learnings.applies_to(everywhere, "design", "custom") == (True, "")


def test_assembly_excludes_a_learning_outside_its_scope_but_keeps_pinned_ones() -> None:
    meta = learnings.normalize_meta(
        {"task_types": ["specification"]}, {"runs": 5, "metric": "m", "baseline": 0.1, "candidate": 0.4}
    )

    def candidate(pinned: bool = False) -> Any:
        return SimpleNamespace(
            memory_kind=MemoryKind.learning, learning_meta=meta, skill_meta=None, pinned=pinned
        )

    inside, outside, pinned = candidate(), candidate(), candidate(pinned=True)
    excluded: list[Any] = []
    kept = _apply_procedure_scope("design", None, [inside, outside, pinned], excluded)
    assert kept == [pinned] and len(excluded) == 2
    assert all(d.verdict.reason_code == ReasonCode.EXCLUDED_SCOPE for d in excluded)
    kept = _apply_procedure_scope("specification", None, [inside, outside], [])
    assert kept == [inside, outside]
