"""Project overview, observability metrics and NDJSON trace export (ARCHITECTURE §11).

Aggregation logic lives in :mod:`app.services.metrics`; this router only resolves access and
formats responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.db import utcnow
from app.deps import OwnerAccess, SessionDep, ViewerAccess
from app.schemas import Metrics, Overview
from app.services import audit
from app.services import metrics as metrics_service
from app.services.audit import AuditAction

router = APIRouter(prefix="/projects/{slug}", tags=["metrics"])

NDJSON_MEDIA_TYPE = "application/x-ndjson"


@router.get("/overview", response_model=Overview, summary="Vue projet")
async def project_overview(access: ViewerAccess, session: SessionDep) -> Overview:
    return await metrics_service.build_overview(session, access)


@router.get("/metrics", response_model=Metrics, summary="Métriques agrégées")
async def project_metrics(
    access: ViewerAccess, session: SessionDep, days: int = Query(default=14, ge=1, le=365)
) -> Metrics:
    return await metrics_service.build_metrics(session, access, days=days)


@router.get(
    "/traces/export",
    response_class=StreamingResponse,
    responses={200: {"content": {NDJSON_MEDIA_TYPE: {}}, "description": "Une ligne JSON par requête"}},
    summary="Export NDJSON des traces (évaluation FORGE)",
)
async def export_traces(
    access: OwnerAccess, session: SessionDep, days: int = Query(default=30, ge=1, le=365)
) -> StreamingResponse:
    since = metrics_service.window_start(days)
    count = await metrics_service.count_requests(session, access.project_id, since)
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.traces_export,
        "project",
        access.project_id,
        summary=f"Export NDJSON de {count} trace(s) de contexte sur {days} jour(s)",
        details={"days": days, "requests": count, "format": "ndjson"},
    )
    await session.commit()
    filename = f"orbit-traces-{access.project.slug}-{utcnow().date().isoformat()}.ndjson"
    return StreamingResponse(
        metrics_service.iter_trace_lines(
            access.project_id, since=since, clearance=int(access.principal.clearance)
        ),
        media_type=NDJSON_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Orbit-Trace-Count": str(count),
        },
    )
