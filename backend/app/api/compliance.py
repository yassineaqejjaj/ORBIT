"""AI Act traceability report export (docs/AI_CONTEXT_ENGINEERING.md §A4) — owners only, audited."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

import orjson
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, Response

from app.db import utcnow
from app.deps import OwnerAccess, SessionDep
from app.errors import validation_error
from app.services import audit
from app.services import compliance as compliance_service
from app.services.audit import AuditAction

router = APIRouter(prefix="/projects/{slug}/compliance", tags=["compliance"])


@router.get(
    "/report",
    summary="Rapport de traçabilité IA (AI Act) : par requête, période ou décision — JSON ou HTML imprimable",
    responses={200: {"content": {"application/json": {}, "text/html": {}}}},
)
async def compliance_report(
    access: OwnerAccess,
    session: SessionDep,
    format: Literal["json", "html"] = Query(default="json"),
    request_id: uuid.UUID | None = Query(default=None, description="Une requête de contexte"),
    memory_id: uuid.UUID | None = Query(default=None, description="Une décision (item mémoire) servie"),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
) -> Response:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise validation_error("La date de début doit précéder la date de fin")
    report: dict[str, Any] = await compliance_service.build_report(
        session,
        access.project,
        clearance=int(access.principal.clearance),
        request_id=request_id,
        memory_id=memory_id,
        since=date_from,
        until=date_to,
    )
    await audit.record(
        session,
        access.project_id,
        access.principal,
        AuditAction.compliance_export,
        "project",
        access.project_id,
        summary=f"Export du rapport de traçabilité IA ({report['totals']['requests']} requête(s), {format})",
        details={"format": format, "scope": report["scope"], "requests": report["totals"]["requests"]},
    )
    await session.commit()
    stem = f"orbit-tracabilite-ia-{access.project.slug}-{utcnow().date().isoformat()}"
    if format == "html":
        return HTMLResponse(
            compliance_service.render_html(report),
            headers={"Content-Disposition": f'inline; filename="{stem}.html"', "Cache-Control": "no-store"},
        )
    return Response(
        orjson.dumps(report, option=orjson.OPT_INDENT_2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{stem}.json"', "Cache-Control": "no-store"},
    )
