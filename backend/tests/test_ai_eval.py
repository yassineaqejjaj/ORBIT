"""Chantier E — evaluation & interoperability (docs/AI_CONTEXT_ENGINEERING.md §E). Fictitious demo data
only; no network (hash embeddings, fake LLM through MockTransport)."""

from __future__ import annotations

import argparse
import math
from typing import Any

import httpx

from app.db import get_sessionmaker
from app.enums import JobKind
from app.evaluation import metrics
from app.ingestion.queue import claim_next_job
from app.worker import Worker
from tests.test_feature_llm import FakeLLM, fake_llm  # noqa: F401

API = "/api/v1/projects"
JSON = dict[str, Any]


async def run_jobs(*kinds: JobKind) -> int:
    worker = Worker(concurrency=1, worker_id="test-eval")
    processed = 0
    for _ in range(50):
        async with get_sessionmaker()() as session:
            job = await claim_next_job(session, worker.worker_id, kinds=kinds)
        if job is None:
            break
        await worker._process(job.id)
        processed += 1
    return processed


async def memory(client: httpx.AsyncClient, slug: str, **body: Any) -> JSON:
    data = {"scope": "project", "kind": "decision", "status": "validated", **body}
    response = await client.post(f"{API}/{slug}/memory", json=data)
    assert response.status_code == 201, response.text
    return response.json()


async def seed_decisions(client: httpx.AsyncClient, slug: str) -> list[JSON]:
    return [
        await memory(
            client,
            slug,
            title="Hébergement du portail Atlas",
            content="Le portail Atlas est hébergé sur le cloud souverain OVH, région Gravelines.",
        ),
        await memory(
            client,
            slug,
            title="Langue de l'interface Atlas",
            content="L'interface du portail Atlas est livrée en français puis en anglais au lot 2.",
        ),
    ]


# --- E1 metrics -------------------------------------------------------------------------------------


def test_metrics_on_toy_set() -> None:
    ranked = [{"a"}, {"x"}, {"b", "b2"}, {"y"}]
    assert metrics.recall_at_k(ranked, ["a", "b"], 2) == 0.5
    assert metrics.recall_at_k(ranked, ["a", "b"], 3) == 1.0
    assert metrics.recall_at_k(ranked, [], 3) == 1.0
    # DCG = 1 + 1/log2(4) ; IDCG = 1 + 1/log2(3)
    expected = (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert abs(metrics.ndcg_at_k(ranked, ["a", "b"], 3) - expected) < 1e-9
    assert metrics.ndcg_at_k([{"a"}, {"b"}], ["a", "b"], 5) == 1.0
    assert metrics.ndcg_at_k([{"z"}], ["a"], 5) == 0.0
    assert metrics.citation_faithfulness("Voir [S1] et [S2], puis [S9].", ["S1", "S2"]) == 2 / 3
    assert metrics.citation_faithfulness("Rien.", []) == 1.0
    assert metrics.citation_faithfulness("Rien.", ["S1"]) == 0.0
    assert metrics.mean([0.5, None, 1.0]) == 0.75


async def test_golden_set_run_job_history_and_compare(admin_client: httpx.AsyncClient, project: JSON) -> None:
    slug = str(project["slug"])
    decisions = await seed_decisions(admin_client, slug)
    created = await admin_client.post(f"{API}/{slug}/evaluation/sets", json={"name": "Référence Atlas"})
    assert created.status_code == 201, created.text
    set_id = created.json()["id"]
    duplicate = await admin_client.post(f"{API}/{slug}/evaluation/sets", json={"name": "Référence Atlas"})
    assert duplicate.status_code == 422

    case = await admin_client.post(
        f"{API}/{slug}/evaluation/sets/{set_id}/cases",
        json={
            "question": "Où est hébergé le portail Atlas ?",
            "expected": [{"type": "memory", "id": decisions[0]["lineage_id"], "title": "Hébergement"}],
        },
    )
    assert case.status_code == 201, case.text
    generated = await admin_client.post(f"{API}/{slug}/evaluation/sets/{set_id}/generate", json={"limit": 5})
    assert generated.status_code == 201, generated.text
    # The first decision is already covered: only the second one is generated (deterministic phrasing).
    assert [c["origin"] for c in generated.json()] == ["generated"]
    assert "Langue de l'interface Atlas" in generated.json()[0]["question"]

    runs = []
    for _ in range(2):
        started = await admin_client.post(f"{API}/{slug}/evaluation/sets/{set_id}/runs", json={"k": 5})
        assert started.status_code == 202, started.text
        assert started.json()["status"] == "queued"
        assert await run_jobs(JobKind.evaluate) == 1
        detail = await admin_client.get(f"{API}/{slug}/evaluation/runs/{started.json()['id']}")
        body = detail.json()
        assert body["status"] == "succeeded", body
        assert body["metrics"]["cases"] == 2
        assert body["metrics"]["recall"] == 1.0 and body["passed"] is True
        assert 0 < body["metrics"]["ndcg"] <= 1
        assert body["metrics"]["citation_faithfulness"] is not None
        assert body["config"]["weights"]["rrf"] > 0
        runs.append(body["id"])

    history = await admin_client.get(f"{API}/{slug}/evaluation/runs")
    assert [r["id"] for r in history.json()][:2] == runs[::-1]
    compared = await admin_client.get(
        f"{API}/{slug}/evaluation/compare", params={"base": runs[0], "target": runs[1]}
    )
    assert compared.status_code == 200
    assert compared.json()["delta"]["recall"] == 0.0 and len(compared.json()["cases"]) == 2
    sets = await admin_client.get(f"{API}/{slug}/evaluation/sets")
    assert sets.json()[0]["cases_count"] == 2 and sets.json()[0]["last_run"]["id"] == runs[1]


async def test_cli_exit_code_follows_threshold(admin_client: httpx.AsyncClient, project: JSON) -> None:
    from app.admin.__main__ import run_eval

    slug = str(project["slug"])
    decisions = await seed_decisions(admin_client, slug)
    set_id = (await admin_client.post(f"{API}/{slug}/evaluation/sets", json={"name": "CI"})).json()["id"]
    await admin_client.post(
        f"{API}/{slug}/evaluation/sets/{set_id}/cases",
        json={
            "question": "Où est hébergé le portail Atlas ?",
            "expected": [{"type": "memory", "id": decisions[0]["lineage_id"]}],
        },
    )
    await admin_client.post(
        f"{API}/{slug}/evaluation/sets/{set_id}/cases",
        json={
            "question": "Quel est le budget du salon de la mobilité 2031 ?",
            "expected": [{"type": "document", "id": "00000000-0000-4000-8000-000000000001"}],
        },
    )

    def args(**kw: Any) -> argparse.Namespace:
        base = {"project": slug, "set_name": None, "k": 5, "min_recall": 0.4, "as_email": None, "json": True}
        return argparse.Namespace(**{**base, **kw})

    assert await run_eval(args()) == 0  # recall 0.5 ≥ 0.4
    assert await run_eval(args(min_recall=0.9)) == 1
    assert await run_eval(args(project="inconnu")) == 2
    assert await run_eval(args(set_name="absent")) == 2
    runs = (await admin_client.get(f"{API}/{slug}/evaluation/runs")).json()
    assert [r["trigger"] for r in runs] == ["cli", "cli"] and [r["passed"] for r in runs] == [False, True]
    overview = await admin_client.get(f"{API}/{slug}/overview")
    if overview.status_code == 200:
        assert any("Évaluation" in a["message"] for a in overview.json()["alerts"])


# --- E2 bounded learning from feedback --------------------------------------------------------------


def test_weight_update_is_bounded() -> None:
    from app.config import settings
    from app.evaluation import learning

    defaults = learning.defaults()
    strong = [{"rrf": 0.0, "dense": 0.0, "freshness": 1.0, "type": 1.0, "terms": 1.0}] * 10
    weak = [{"rrf": 1.0, "dense": 1.0, "freshness": 0.0, "type": 0.0, "terms": 0.0}] * 10
    current = dict(defaults)
    for _ in range(20):  # repeated steps never escape the bounds
        current = learning.propose(current, strong, weak)
    delta = settings.ranking_learning_max_delta
    for key, value in current.items():
        assert defaults[key] - delta - 1e-6 <= value <= defaults[key] + delta + 1e-6, (key, value)
    assert current["freshness"] > defaults["freshness"] and current["rrf"] < defaults["rrf"]
    assert abs(sum(current.values()) - 1.0) < 0.05


async def test_learning_from_feedback_is_logged_and_reversible(
    admin_client: httpx.AsyncClient, project: JSON, monkeypatch: Any
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ranking_learning_min_signals", 2)
    slug = str(project["slug"])
    await seed_decisions(admin_client, slug)
    initial = (await admin_client.get(f"{API}/{slug}/evaluation/ranking-weights")).json()
    assert initial["weights"] == initial["defaults"] and initial["history"] == []

    none_yet = await admin_client.post(f"{API}/{slug}/evaluation/ranking-weights/learn")
    assert none_yet.json()["outcome"] == "unchanged"
    for task, rating in (("Où est hébergé le portail Atlas ?", 5), ("Langue de l'interface Atlas", 1)):
        package = (
            await admin_client.post(f"{API}/{slug}/context", json={"task": task, "min_relevance": 0})
        ).json()
        flags = (
            [{"citation": package["items"][-1]["citation"], "flag": "irrelevant"}] if rating == 1 else None
        )
        sent = await admin_client.post(
            f"{API}/{slug}/context/requests/{package['request_id']}/feedback",
            json={"rating": rating, "item_flags": flags},
        )
        assert sent.status_code in (200, 201), sent.text

    learned = (await admin_client.post(f"{API}/{slug}/evaluation/ranking-weights/learn")).json()
    assert learned["outcome"] == "adjusted", learned
    change = learned["history"][0]
    assert change["reason"] == "learn" and change["signals"]["feedback"] == 2
    assert change["before"] == initial["defaults"] and change["after"] == learned["weights"]
    for key, (low, high) in learned["bounds"].items():
        assert low - 1e-6 <= learned["weights"][key] <= high + 1e-6
    # Learned weights are used by the engine.
    package = (
        await admin_client.post(f"{API}/{slug}/context", json={"task": "Atlas", "min_relevance": 0})
    ).json()
    assert package["items"]

    reverted = (
        await admin_client.post(f"{API}/{slug}/evaluation/ranking-weights/{change['id']}/revert")
    ).json()
    assert reverted["weights"] == initial["defaults"] and reverted["history"][0]["reason"] == "revert"
    again = await admin_client.post(f"{API}/{slug}/evaluation/ranking-weights/{change['id']}/revert")
    assert again.status_code == 422
    audit = (await admin_client.get(f"{API}/{slug}/audit", params={"action": "evaluation"})).json()
    items = audit.get("items", audit) if isinstance(audit, dict) else audit
    assert sum(1 for a in items if a["action"] == "evaluation.ranking_weights") == 2


# --- E3 LLM judge -----------------------------------------------------------------------------------


async def test_judge_sampling_guardrail_alert_and_export(
    admin_client: httpx.AsyncClient,
    project: JSON,
    fake_llm: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    import json

    from app.config import settings
    from app.evaluation import judge
    from app.llm import guardrail

    slug = str(project["slug"])
    assert judge.should_sample(0.0) is False and judge.should_sample(1.0) is True
    fake = fake_llm(
        lambda _p: '{"score": 0.2, "verdict": "insufficient", "explanation": "Il manque le budget."}'
    )
    monkeypatch.setattr(settings, "judge_sample_rate", 1.0)
    monkeypatch.setattr(settings, "judge_min_samples", 2)
    await memory(
        admin_client, slug, title="Budget du salon Atlas", content="Le budget du salon Atlas est de 80 k€."
    )
    await memory(
        admin_client,
        slug,
        title="Budget confidentiel Atlas",
        content="Enveloppe confidentielle du salon Atlas : 95 k€.",
        classification=2,
    )
    for task, level in (("Budget du salon Atlas", 1), ("Enveloppe confidentielle du salon Atlas", 3)):
        response = await admin_client.post(
            f"{API}/{slug}/context", json={"task": task, "min_relevance": 0, "max_classification": level}
        )
        assert response.status_code == 200
    skips = guardrail.skip_count()
    assert await run_jobs(JobKind.judge) == 2
    listing = (await admin_client.get(f"{API}/{slug}/evaluation/judgements")).json()
    methods = {item["task"]: item for item in listing["items"]}
    assert methods["Budget du salon Atlas"]["method"] == "llm"
    assert methods["Budget du salon Atlas"]["score"] == 0.2
    confidential = methods["Enveloppe confidentielle du salon Atlas"]
    assert confidential["method"] == "skipped_guardrail"  # C2: never sent to the external LLM
    assert guardrail.skip_count() > skips
    assert all("95 k€" not in json.dumps(b) for b in fake.bodies())
    assert len(fake.bodies()) == 1

    monkeypatch.setattr(settings, "judge_alert_threshold", 0.99)
    listing = (await admin_client.get(f"{API}/{slug}/evaluation/judgements")).json()
    assert listing["window_count"] == 2 and listing["alerts"]
    overview = await admin_client.get(f"{API}/{slug}/overview")
    assert any("LLM-juge" in a["message"] for a in overview.json()["alerts"])

    exported = await admin_client.get(f"{API}/{slug}/evaluation/judgements/export")
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in exported.text.splitlines()]
    assert {line["type"] for line in lines} == {"orbit.context_judgement"} and len(lines) == 2
    assert all("context" not in line for line in lines)
