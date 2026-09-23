"""Project overview, metrics and trace export (STUB — implemented by the observability teammate)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.deps import OwnerAccess, SessionDep, ViewerAccess
from app.schemas import Metrics, Overview

router = APIRouter(prefix="/projects/{slug}", tags=["metrics"])


@router.get("/overview", response_model=Overview, summary="Vue projet")
async def project_overview(access: ViewerAccess, session: SessionDep) -> Overview:
    raise NotImplementedError


@router.get("/metrics", response_model=Metrics, summary="Métriques agrégées")
async def project_metrics(
    access: ViewerAccess, session: SessionDep, days: int = Query(default=14, ge=1, le=365)
) -> Metrics:
    raise NotImplementedError


@router.get(
    "/traces/export",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/x-ndjson": {}}, "description": "Une ligne JSON par requête"}},
    summary="Export NDJSON des traces (évaluation FORGE)",
)
async def export_traces(
    access: OwnerAccess, session: SessionDep, days: int = Query(default=30, ge=1, le=365)
) -> StreamingResponse:
    raise NotImplementedError
