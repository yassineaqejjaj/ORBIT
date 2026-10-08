"""Evaluation & learning (docs/AI_CONTEXT_ENGINEERING.md §E1–E3): golden sets, runs and comparison,
bounded ranking weights learned from feedback, LLM-judge verdicts and their FORGE export."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.deps import EditorAccess, OwnerAccess, SessionDep, ViewerAccess
from app.errors import not_found, validation_error
from app.evaluation import bench
from app.models import EvalCase, EvalRun, EvalSet
from app.schemas.common import ApiModel, InputModel
from app.services import audit
from app.services.audit import AuditAction

router = APIRouter(prefix="/projects/{slug}/evaluation", tags=["evaluation"])

SET_NOT_FOUND = "Jeu d'évaluation introuvable"
RUN_NOT_FOUND = "Exécution d'évaluation introuvable"


class ExpectedItem(InputModel):
    type: Literal["memory", "document"] = "memory"
    id: uuid.UUID
    title: str = Field(default="", max_length=300)


class EvalCaseIn(InputModel):
    question: str = Field(min_length=3, max_length=2000)
    expected: list[ExpectedItem] = Field(default_factory=list, max_length=50)


class EvalCaseOut(ApiModel):
    id: uuid.UUID
    question: str
    expected: list[dict[str, Any]]
    origin: str
    created_at: datetime


class EvalSetIn(InputModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class EvalSetOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    cases_count: int = 0
    last_run: EvalRunSummary | None = None
    created_at: datetime


class EvalSetDetail(EvalSetOut):
    cases: list[EvalCaseOut] = Field(default_factory=list)


class EvalRunSummary(ApiModel):
    id: uuid.UUID
    set_id: uuid.UUID
    status: str
    trigger: str
    k: int
    min_recall: float | None
    metrics: dict[str, Any]
    passed: bool | None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class EvalRunOut(EvalRunSummary):
    cases: list[dict[str, Any]]
    config: dict[str, Any]


class EvalRunIn(InputModel):
    k: int | None = Field(default=None, ge=1, le=50)
    min_recall: float | None = Field(default=None, ge=0, le=1)


class GenerateIn(InputModel):
    limit: int = Field(default=10, ge=1, le=50)


class CompareOut(ApiModel):
    base: EvalRunSummary
    target: EvalRunSummary
    delta: dict[str, float | None]
    cases: list[dict[str, Any]]


EvalSetOut.model_rebuild()
EvalSetDetail.model_rebuild()


async def _set(session: AsyncSession, project_id: uuid.UUID, set_id: uuid.UUID) -> EvalSet:
    row = await session.get(EvalSet, set_id)
    if row is None or row.project_id != project_id:
        raise not_found(SET_NOT_FOUND)
    return row


async def _run(session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID) -> EvalRun:
    row = await session.get(EvalRun, run_id)
    if row is None or row.project_id != project_id:
        raise not_found(RUN_NOT_FOUND)
    return row


async def _set_out(session: AsyncSession, row: EvalSet, *, detail: bool = False) -> EvalSetOut:
    cases = list(
        await session.scalars(select(EvalCase).where(EvalCase.set_id == row.id).order_by(EvalCase.created_at))
    )
    last = await session.scalar(
        select(EvalRun).where(EvalRun.set_id == row.id).order_by(EvalRun.created_at.desc()).limit(1)
    )
    data: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "cases_count": len(cases),
        "last_run": EvalRunSummary.model_validate(last) if last else None,
        "created_at": row.created_at,
    }
    if detail:
        return EvalSetDetail(**data, cases=[EvalCaseOut.model_validate(c) for c in cases])
    return EvalSetOut(**data)


async def _audit_set(session: AsyncSession, access: Any, row: EvalSet, summary: str) -> None:
    await audit.record(
        session, access.project_id, access.principal, AuditAction.eval_set_change, "eval_set", row.id, summary
    )


# --- Golden sets ------------------------------------------------------------------------------------


@router.get("/sets", response_model=list[EvalSetOut], summary="Jeux de questions de référence")
async def list_sets(access: ViewerAccess, session: SessionDep) -> list[EvalSetOut]:
    rows = await session.scalars(
        select(EvalSet).where(EvalSet.project_id == access.project_id).order_by(EvalSet.name)
    )
    return [await _set_out(session, row) for row in rows]


@router.post(
    "/sets", response_model=EvalSetDetail, status_code=status.HTTP_201_CREATED, summary="Créer un jeu"
)
async def create_set(body: EvalSetIn, access: EditorAccess, session: SessionDep) -> EvalSetOut:
    exists = await session.scalar(
        select(func.count()).where(EvalSet.project_id == access.project_id, EvalSet.name == body.name)
    )
    if exists:
        raise validation_error(f"Un jeu « {body.name} » existe déjà")
    row = EvalSet(
        project_id=access.project_id,
        name=body.name,
        description=body.description,
        created_by=access.principal.user.id if access.principal.user else None,
    )
    session.add(row)
    await session.flush()
    await _audit_set(session, access, row, f"Jeu d'évaluation « {row.name} » créé")
    await session.commit()
    return await _set_out(session, row, detail=True)


@router.get("/sets/{set_id}", response_model=EvalSetDetail, summary="Détail d'un jeu")
async def get_set(set_id: uuid.UUID, access: ViewerAccess, session: SessionDep) -> EvalSetOut:
    return await _set_out(session, await _set(session, access.project_id, set_id), detail=True)


@router.delete("/sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un jeu")
async def delete_set(set_id: uuid.UUID, access: OwnerAccess, session: SessionDep) -> None:
    row = await _set(session, access.project_id, set_id)
    await _audit_set(session, access, row, f"Jeu d'évaluation « {row.name} » supprimé")
    await session.delete(row)
    await session.commit()


@router.post(
    "/sets/{set_id}/cases", response_model=EvalCaseOut, status_code=status.HTTP_201_CREATED, summary="Ajouter"
)
async def add_case(
    set_id: uuid.UUID, body: EvalCaseIn, access: EditorAccess, session: SessionDep
) -> EvalCase:
    row = await _set(session, access.project_id, set_id)
    case = EvalCase(
        set_id=row.id, question=body.question, expected=[e.model_dump(mode="json") for e in body.expected]
    )
    session.add(case)
    await session.flush()
    await _audit_set(session, access, row, f"Question ajoutée au jeu « {row.name} »")
    await session.commit()
    return case


@router.delete("/sets/{set_id}/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Retirer")
async def delete_case(
    set_id: uuid.UUID, case_id: uuid.UUID, access: EditorAccess, session: SessionDep
) -> None:
    row = await _set(session, access.project_id, set_id)
    deleted = await session.execute(delete(EvalCase).where(EvalCase.id == case_id, EvalCase.set_id == row.id))
    if not deleted.rowcount:  # type: ignore[attr-defined]
        raise not_found("Question introuvable")
    await _audit_set(session, access, row, f"Question retirée du jeu « {row.name} »")
    await session.commit()


@router.post(
    "/sets/{set_id}/generate",
    response_model=list[EvalCaseOut],
    status_code=status.HTTP_201_CREATED,
    summary="Génération assistée depuis les décisions validées",
)
async def generate(
    set_id: uuid.UUID, access: EditorAccess, session: SessionDep, body: GenerateIn | None = None
) -> list[EvalCase]:
    row = await _set(session, access.project_id, set_id)
    created = await bench.generate_cases(
        session, row, limit=(body or GenerateIn()).limit, viewer_clearance=int(access.principal.clearance)
    )
    if created:
        await _audit_set(session, access, row, f"{len(created)} question(s) générée(s) depuis les décisions")
    await session.commit()
    return created


# --- Runs -------------------------------------------------------------------------------------------


@router.post(
    "/sets/{set_id}/runs",
    response_model=EvalRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lancer une évaluation (tâche de fond)",
)
async def start_run(
    set_id: uuid.UUID, access: EditorAccess, session: SessionDep, body: EvalRunIn | None = None
) -> EvalRun:
    row = await _set(session, access.project_id, set_id)
    user = access.principal.user
    if user is None:
        raise validation_error("Une évaluation est lancée par un utilisateur")
    params = body or EvalRunIn()
    run = await bench.create_run(session, row, user=user, k=params.k, min_recall=params.min_recall)
    await session.commit()
    return run


@router.get("/runs", response_model=list[EvalRunSummary], summary="Historique des évaluations")
async def list_runs(
    access: ViewerAccess,
    session: SessionDep,
    set_id: uuid.UUID | None = None,
    limit: int = Query(default=30, ge=1, le=200),
) -> list[EvalRun]:
    query = select(EvalRun).where(EvalRun.project_id == access.project_id)
    if set_id is not None:
        query = query.where(EvalRun.set_id == set_id)
    return list(await session.scalars(query.order_by(EvalRun.created_at.desc()).limit(limit)))


@router.get("/runs/{run_id}", response_model=EvalRunOut, summary="Détail d'une évaluation")
async def get_run(run_id: uuid.UUID, access: ViewerAccess, session: SessionDep) -> EvalRun:
    return await _run(session, access.project_id, run_id)


@router.get("/compare", response_model=CompareOut, summary="Comparer deux évaluations")
async def compare(
    base: uuid.UUID, target: uuid.UUID, access: ViewerAccess, session: SessionDep
) -> CompareOut:
    a = await _run(session, access.project_id, base)
    b = await _run(session, access.project_id, target)
    delta: dict[str, float | None] = {}
    for key in ("recall", "ndcg", "sufficiency", "citation_faithfulness"):
        va, vb = (a.metrics or {}).get(key), (b.metrics or {}).get(key)
        delta[key] = round(vb - va, 4) if va is not None and vb is not None else None
    by_case = {c.get("case_id"): c for c in a.cases or []}
    cases = [
        {
            "case_id": c.get("case_id"),
            "question": c.get("question"),
            "base_recall": by_case.get(c.get("case_id"), {}).get("recall"),
            "target_recall": c.get("recall"),
        }
        for c in b.cases or []
    ]
    return CompareOut(
        base=EvalRunSummary.model_validate(a),
        target=EvalRunSummary.model_validate(b),
        delta=delta,
        cases=cases,
    )


@router.get("/settings", summary="Réglages d'évaluation en vigueur")
async def eval_settings(access: ViewerAccess) -> dict[str, Any]:
    return {
        "k": settings.eval_k,
        "min_recall": settings.eval_min_recall,
        "ranking_learning": settings.ranking_learning,
        "ranking_learning_max_delta": settings.ranking_learning_max_delta,
        "judge_sample_rate": settings.judge_sample_rate,
        "judge_alert_threshold": settings.judge_alert_threshold,
    }


# --- §E2 ranking weights learned from feedback ------------------------------------------------------


async def _weights_view(
    session: AsyncSession, project_id: uuid.UUID, outcome: str | None = None
) -> dict[str, Any]:
    from app.evaluation import learning
    from app.models import RankingWeightChange

    history = await session.scalars(
        select(RankingWeightChange)
        .where(RankingWeightChange.project_id == project_id)
        .order_by(RankingWeightChange.created_at.desc(), RankingWeightChange.id.desc())
        .limit(50)
    )
    return {
        "enabled": settings.ranking_learning,
        "weights": await learning.current_weights(session, project_id),
        "defaults": learning.defaults(),
        "bounds": {k: list(v) for k, v in learning.bounds().items()},
        "max_delta": settings.ranking_learning_max_delta,
        "min_signals": settings.ranking_learning_min_signals,
        "history": learning.describe(history),
        "outcome": outcome,
    }


@router.get("/ranking-weights", summary="Poids du classement du projet (appris, bornés)")
async def ranking_weights(access: ViewerAccess, session: SessionDep) -> dict[str, Any]:
    return await _weights_view(session, access.project_id)


@router.post("/ranking-weights/learn", summary="Ajuster les poids d'après les retours")
async def learn_weights(access: OwnerAccess, session: SessionDep) -> dict[str, Any]:
    from app.evaluation import learning

    if not settings.ranking_learning:
        raise validation_error("L'apprentissage des poids est désactivé (ORBIT_RANKING_LEARNING)")
    change = await learning.learn(session, access.project_id, access.principal)
    await session.commit()
    outcome = "adjusted" if change is not None else "unchanged"
    return await _weights_view(session, access.project_id, outcome)


@router.post("/ranking-weights/{change_id}/revert", summary="Annuler un ajustement des poids")
async def revert_weights(change_id: uuid.UUID, access: OwnerAccess, session: SessionDep) -> dict[str, Any]:
    from app.evaluation import learning
    from app.models import RankingWeightChange

    change = await session.get(RankingWeightChange, change_id)
    if change is None or change.project_id != access.project_id:
        raise not_found("Ajustement introuvable")
    if change.reverted_at is not None:
        raise validation_error("Cet ajustement a déjà été annulé")
    await learning.revert(session, access.project_id, change, access.principal)
    await session.commit()
    return await _weights_view(session, access.project_id, "reverted")


@router.post("/ranking-weights/reset", summary="Revenir aux poids par défaut")
async def reset_weights(access: OwnerAccess, session: SessionDep) -> dict[str, Any]:
    from app.evaluation import learning

    await learning.reset(session, access.project_id, access.principal)
    await session.commit()
    return await _weights_view(session, access.project_id, "reset")


# --- §E3 LLM judge ----------------------------------------------------------------------------------


@router.get("/judgements", summary="Verdicts du LLM-juge (échantillon des contextes servis)")
async def list_judgements(
    access: ViewerAccess, session: SessionDep, limit: int = Query(default=50, ge=1, le=500)
) -> dict[str, Any]:
    from app.evaluation import judge
    from app.models import ContextJudgement, ContextRequest

    rows = await session.execute(
        select(ContextJudgement, ContextRequest)
        .join(ContextRequest, ContextRequest.id == ContextJudgement.request_id)
        .where(ContextJudgement.project_id == access.project_id)
        .order_by(ContextJudgement.created_at.desc())
        .limit(limit)
    )
    count, average = await judge.window_stats(session, access.project_id)
    return {
        "sample_rate": settings.judge_sample_rate,
        "threshold": settings.judge_alert_threshold,
        "window_days": settings.judge_window_days,
        "window_count": count,
        "window_average": round(average, 3) if average is not None else None,
        "alerts": await judge.degradation_alerts(session, access.project_id),
        "items": [judge.export_row(j, r) for j, r in rows],
    }


@router.get(
    "/judgements/export",
    response_class=StreamingResponse,
    summary="Export NDJSON des verdicts pour FORGE",
)
async def export_judgements(
    access: OwnerAccess, session: SessionDep, days: int = Query(default=30, ge=1, le=365)
) -> StreamingResponse:
    from app.evaluation import judge
    from app.models import ContextJudgement, ContextRequest

    since = utcnow() - timedelta(days=days)
    rows = list(
        await session.execute(
            select(ContextJudgement, ContextRequest)
            .join(ContextRequest, ContextRequest.id == ContextJudgement.request_id)
            .where(ContextJudgement.project_id == access.project_id, ContextJudgement.created_at >= since)
            .order_by(ContextJudgement.created_at)
        )
    )
    lines = [json.dumps(judge.export_row(j, r), ensure_ascii=False) + "\n" for j, r in rows]
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.judge_export,
        "context_judgements",
        None,
        summary=f"Export FORGE des verdicts du LLM-juge ({len(lines)} sur {days} j)",
        details={"days": days, "count": len(lines)},
    )
    await session.commit()
    filename = f"orbit-judgements-{access.project.slug}.ndjson"
    return StreamingResponse(
        iter(lines),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
