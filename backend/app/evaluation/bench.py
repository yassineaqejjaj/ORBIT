"""§E1 evaluation bench: golden sets, assisted generation from validated decisions, runs as jobs.

A run replays every reference question through the real context engine (``assemble_context``) **as the
user who launched it** (same governance: ACL, clearance, private memory, audit) and measures:

* ``recall@k`` / ``nDCG@k`` of the expected items (memory lineages or documents) in the served ranking;
* ``sufficiency`` — the §C5 sufficiency score of each served context;
* ``citation_faithfulness`` — citation markers of the served text that point to a served item.

The served requests are tagged ``params.evaluation = <run id>`` (excluded from the §E3 judge sample).
A run passes when its mean recall ≥ ``min_recall`` (``ORBIT_EVAL_MIN_RECALL`` by default). The CLI
(``python -m app.admin eval``) runs the same code synchronously and exits non-zero below the threshold.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.deps import Principal, ProjectAccess
from app.enums import JobKind, MemoryKind, MemoryScope, MemoryStatus, Role
from app.evaluation import metrics
from app.llm import client as llm_client
from app.llm import guardrail
from app.models import ContextRequest, EvalCase, EvalRun, EvalSet, IngestionJob, MemoryItem, Project, User
from app.schemas import ContextPackage, ContextRequestIn
from app.services import audit
from app.services.audit import Actor, AuditAction

logger = logging.getLogger("orbit.evaluation")

GENERATE_SYSTEM = (
    "Tu rédiges des questions d'évaluation pour un moteur de contexte. À partir d'une décision de projet, "
    "écris UNE question en français, naturelle, à laquelle cette décision répond, sans recopier le titre. "
    'Réponds en JSON : {"question": "..."}.'
)


def expected_keys(expected: Sequence[dict[str, Any]]) -> list[str]:
    return [f"{e.get('type', 'memory')}:{e.get('id')}" for e in expected if e.get("id")]


async def item_keys(session: AsyncSession, package: ContextPackage) -> list[set[str]]:
    """Keys of each served item in rank order (memory id + lineage, document id)."""
    memory_ids = [i.memory_item_id for i in package.items if i.memory_item_id]
    lineages: dict[uuid.UUID, uuid.UUID] = {}
    if memory_ids:
        rows = await session.execute(
            select(MemoryItem.id, MemoryItem.lineage_id).where(MemoryItem.id.in_(memory_ids))
        )
        lineages = {row[0]: row[1] for row in rows}
    ranked: list[set[str]] = []
    for item in package.items:
        keys: set[str] = set()
        if item.memory_item_id:
            keys.add(f"memory:{item.memory_item_id}")
            if item.memory_item_id in lineages:
                keys.add(f"memory:{lineages[item.memory_item_id]}")
        if item.document_id:
            keys.add(f"document:{item.document_id}")
        ranked.append(keys)
    return ranked


def score_case(
    ranked: Sequence[set[str]], expected: Sequence[str], text: str, citations: Sequence[str], k: int
) -> dict[str, float]:
    return {
        "recall": round(metrics.recall_at_k(ranked, expected, k), 4),
        "ndcg": round(metrics.ndcg_at_k(ranked, expected, k), 4),
        "citation_faithfulness": round(metrics.citation_faithfulness(text, citations), 4),
    }


# --- Golden sets ------------------------------------------------------------------------------------


async def generate_cases(
    session: AsyncSession, eval_set: EvalSet, *, limit: int = 10, viewer_clearance: int = 3
) -> list[EvalCase]:
    """Assisted generation: one case per validated decision not yet covered (LLM phrasing when the
    guardrail allows, deterministic template otherwise). Cases are created with ``origin=generated``."""
    covered = {
        str(e.get("id"))
        for expected in await session.scalars(select(EvalCase.expected).where(EvalCase.set_id == eval_set.id))
        for e in expected or []
    }
    decisions = await session.scalars(
        select(MemoryItem)
        .where(
            MemoryItem.project_id == eval_set.project_id,
            MemoryItem.is_current.is_(True),
            MemoryItem.kind == MemoryKind.decision,
            MemoryItem.status == MemoryStatus.validated,
            MemoryItem.scope.in_([MemoryScope.project, MemoryScope.long_term]),
            MemoryItem.classification <= viewer_clearance,
        )
        .order_by(MemoryItem.updated_at.desc())
    )
    created: list[EvalCase] = []
    for item in decisions:
        if len(created) >= limit:
            break
        if str(item.lineage_id) in covered:
            continue
        question = await _phrase(item)
        case = EvalCase(
            set_id=eval_set.id,
            question=question,
            expected=[{"type": "memory", "id": str(item.lineage_id), "title": item.title}],
            origin="generated",
        )
        session.add(case)
        created.append(case)
    await session.flush()
    return created


async def _phrase(item: MemoryItem) -> str:
    fallback = f"Quelle décision a été prise concernant « {item.title} » ?"
    if not llm_client.is_enabled():
        return fallback
    level = int(item.classification)
    if not guardrail.allows(level):
        guardrail.record_skip(guardrail.REASON_CLASSIFICATION)
        return fallback
    data = await llm_client.complete_json(
        GENERATE_SYSTEM,
        f"Titre : {item.title}\n\n{item.content[:2000]}",
        classification=level,
        max_tokens=120,
    )
    question = data.get("question") if isinstance(data, dict) else None
    if isinstance(question, str) and 8 <= len(question.strip()) <= 500:
        return " ".join(question.split())
    return fallback


# --- Runs -------------------------------------------------------------------------------------------


async def create_run(
    session: AsyncSession,
    eval_set: EvalSet,
    *,
    user: User,
    k: int | None = None,
    min_recall: float | None = None,
    trigger: str = "ui",
    enqueue: bool = True,
) -> EvalRun:
    from app.ingestion.queue import enqueue_job

    run = EvalRun(
        project_id=eval_set.project_id,
        set_id=eval_set.id,
        status="queued",
        trigger=trigger,
        k=k or settings.eval_k,
        min_recall=settings.eval_min_recall if min_recall is None else min_recall,
        config={"user_id": str(user.id)},
    )
    session.add(run)
    await session.flush()
    if enqueue:
        job = await enqueue_job(
            session,
            eval_set.project_id,
            JobKind.evaluate,
            payload={"run_id": str(run.id), "user_id": str(user.id)},
            max_attempts=1,
        )
        run.job_id = job.id
    return run


async def execute_run(session: AsyncSession, run: EvalRun) -> EvalRun:
    """Replay the golden set and store the metrics (commits through ``assemble_context``)."""
    from app.context import rerank
    from app.context.assembler import assemble_context
    from app.evaluation import learning

    project = await session.get(Project, run.project_id)
    user = await session.get(User, uuid.UUID(str(run.config.get("user_id"))))
    if project is None or user is None:
        raise ValueError("Projet ou utilisateur de l'évaluation introuvable")
    eval_set = await session.get(EvalSet, run.set_id)
    cases = list(
        await session.scalars(
            select(EvalCase).where(EvalCase.set_id == run.set_id).order_by(EvalCase.created_at)
        )
    )
    run_id, k, set_name = run.id, run.k, eval_set.name if eval_set else ""
    weights = await learning.current_weights(session, project.id)
    run.status = "running"
    run.config = {
        **run.config,
        "reranker": rerank.reranker_label(),
        "weights": weights,
        "set_name": set_name,
        "cases": len(cases),
    }
    await session.commit()

    access = ProjectAccess(project=project, principal=Principal.for_user(user), role=Role.owner)
    details: list[dict[str, Any]] = []
    for case in cases:
        expected = expected_keys(case.expected or [])
        question, case_id = case.question, case.id
        package = await assemble_context(
            session, access, ContextRequestIn(task=question, explain=False, min_relevance=0), emit_events=False
        )
        request = await session.get(ContextRequest, package.request_id)
        if request is not None:
            request.params = {**(request.params or {}), "evaluation": str(run_id)}
        ranked = await item_keys(session, package)
        scores = score_case(ranked, expected, package.context, [i.citation for i in package.items], k)
        sufficiency = package.sufficiency.score if package.sufficiency else None
        details.append(
            {
                "case_id": str(case_id),
                "question": question,
                "expected": len(expected),
                "found": [
                    i.title for i, keys in zip(package.items, ranked, strict=True) if keys & set(expected)
                ],
                "request_id": str(package.request_id),
                "sufficiency": sufficiency,
                **scores,
            }
        )
        await session.commit()

    run = await session.get(EvalRun, run_id)  # type: ignore[assignment]
    aggregated = {
        "recall": metrics.mean(d["recall"] for d in details),
        "ndcg": metrics.mean(d["ndcg"] for d in details),
        "sufficiency": metrics.mean(d["sufficiency"] for d in details),
        "citation_faithfulness": metrics.mean(d["citation_faithfulness"] for d in details),
        "cases": len(details),
    }
    run.metrics = aggregated
    run.cases = details
    run.status = "succeeded"
    run.finished_at = utcnow()
    recall = aggregated["recall"]
    run.passed = None if recall is None else recall >= float(run.min_recall or 0)
    await audit.record(
        session,
        run.project_id,
        Actor.from_user(user),
        AuditAction.eval_run,
        "eval_run",
        run.id,
        summary=(
            f"Évaluation « {set_name} » : rappel@{k} {recall if recall is not None else '—'}, "
            f"{'réussie' if run.passed else 'sous le seuil' if run.passed is False else 'sans question'}"
        ),
        details={"metrics": aggregated, "min_recall": run.min_recall, "trigger": run.trigger},
    )
    await session.commit()
    return run


async def handle_evaluate(session: AsyncSession, job: IngestionJob) -> None:
    """Job handler (``evaluate``): payload ``{"run_id"}``."""
    run_id = uuid.UUID(str((job.payload or {}).get("run_id")))
    run = await session.get(EvalRun, run_id)
    if run is None:
        return
    try:
        await execute_run(session, run)
    except Exception as exc:
        await session.rollback()
        failed = await session.get(EvalRun, run_id)
        if failed is not None:
            failed.status = "failed"
            failed.error = f"{type(exc).__name__}: {exc}"[:500]
            failed.finished_at = utcnow()
            await session.commit()
        raise


async def regression_alerts(session: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """Attention-list messages: last run below its threshold, or recall dropped vs. the previous run."""
    runs = list(
        await session.scalars(
            select(EvalRun)
            .where(EvalRun.project_id == project_id, EvalRun.status == "succeeded")
            .order_by(EvalRun.created_at.desc())
            .limit(2)
        )
    )
    if not runs:
        return []
    last = runs[0]
    recall = (last.metrics or {}).get("recall")
    messages: list[str] = []
    if last.passed is False and recall is not None:
        messages.append(
            f"Évaluation : rappel@{last.k} {recall:.2f} sous le seuil {float(last.min_recall or 0):.2f} "
            "— la qualité du contexte s'est dégradée."
        )
    elif len(runs) == 2 and recall is not None:
        previous = (runs[1].metrics or {}).get("recall")
        if previous is not None and previous - recall >= 0.1:
            messages.append(
                f"Évaluation : rappel en baisse ({previous:.2f} → {recall:.2f}) depuis le dernier passage."
            )
    return messages


__all__ = [
    "create_run",
    "execute_run",
    "expected_keys",
    "generate_cases",
    "handle_evaluate",
    "item_keys",
    "regression_alerts",
    "score_case",
]
