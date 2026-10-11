"""Validated learnings (ORION): improvements verified by an evaluation, kept with their scope and evidence.

FORGE (or any evaluator with an agent key) submits a learning once an improvement held on several runs. It
arrives as a **proposal** in the usual memory workflow: a human validates it before it is served as validated
knowledge. ORBIT checks the evidence is a real, sufficient improvement; it does not re-run the evaluation.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import AgentEditorAccess, AgentViewerAccess, SessionDep
from app.enums import MemoryKind, MemoryScope, MemoryStatus
from app.errors import validation_error
from app.memory import learnings, lifecycle
from app.memory.serializers import serialize_items
from app.memory.visibility import MemoryViewer, visibility_clause
from app.models import MemoryItem as MemoryItemRow
from app.schemas import MemoryIn, MemoryItem, Page, PageParams, page_params
from app.schemas.common import make_page
from app.schemas.memory import LearningIn, ProvenanceIn

router = APIRouter(prefix="/projects/{slug}/learnings", tags=["learnings"])


@router.post(
    "",
    response_model=MemoryItem,
    status_code=status.HTTP_201_CREATED,
    summary="Soumettre un apprentissage vérifié (proposé à la validation)",
)
async def submit_learning(body: LearningIn, access: AgentEditorAccess, session: SessionDep) -> MemoryItem:
    evidence = body.evidence
    minimum = get_settings().learning_min_runs
    if evidence.runs < minimum:
        raise validation_error(f"Preuve insuffisante : {evidence.runs} run(s) comparés, {minimum} requis")
    if evidence.candidate <= evidence.baseline:
        raise validation_error("Preuve insuffisante : la variante n'améliore pas la référence")
    if body.scope not in (MemoryScope.project, MemoryScope.long_term):
        raise validation_error("Un apprentissage est rattaché au projet ou à la mémoire long terme")
    meta = learnings.normalize_meta(body.applies_to, evidence)
    shift = f"{evidence.metric} {evidence.baseline:g} → {evidence.candidate:g}"
    label = f"{evidence.source} · {shift} sur {evidence.runs} runs"
    data = MemoryIn(
        scope=body.scope,
        kind=MemoryKind.learning,
        title=body.title,
        content=body.content,
        classification=body.classification,
        tags=body.tags,
        provenance=[
            ProvenanceIn(
                source_label=label[:300],
                excerpt=(f"experiment={evidence.experiment_id or '-'} suite={evidence.eval_suite_id or '-'}")[
                    :4000
                ],
            )
        ],
    )
    item = await lifecycle.create_item(
        session,
        project_id=access.project_id,
        data=data,
        actor=access.principal.actor,
        force_status=MemoryStatus.proposed.value,
        learning_meta=meta,
    )
    await session.commit()
    return (await serialize_items(session, [item]))[0]


@router.get("", response_model=Page[MemoryItem], summary="Apprentissages du projet")
async def list_learnings(
    access: AgentViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    status_: Annotated[MemoryStatus | None, Query(alias="status")] = None,
) -> Page[MemoryItem]:
    viewer = MemoryViewer.from_access(access)
    query = select(MemoryItemRow).where(
        MemoryItemRow.project_id == access.project_id,
        MemoryItemRow.kind == MemoryKind.learning,
        MemoryItemRow.is_current.is_(True),
        visibility_clause(viewer),
    )
    if status_ is not None:
        query = query.where(MemoryItemRow.status == status_)
    rows = list(
        await session.scalars(
            query.order_by(MemoryItemRow.created_at.desc()).offset(params.offset).limit(params.limit)
        )
    )
    total = len(list(await session.scalars(query.with_only_columns(MemoryItemRow.id).order_by(None))))
    return make_page(await serialize_items(session, rows), total, params)
