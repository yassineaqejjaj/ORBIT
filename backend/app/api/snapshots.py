"""Context snapshots (API.md « Snapshots »). Services live in ``app.context.snapshots``.

Route order matters: ``/{name}/diff`` is declared before ``/{name}/{version}``.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import snapshots as service
from app.context.visibility import Viewer
from app.deps import AgentViewerAccess, ProjectAccess, SessionDep, ViewerAccess
from app.errors import not_found, validation_error
from app.models import ContextSnapshot
from app.schemas import Snapshot, SnapshotDiff, SnapshotGroup, SnapshotSummary

router = APIRouter(prefix="/projects/{slug}/snapshots", tags=["snapshots"])

NOT_FOUND = "Snapshot introuvable"


async def _load(
    session: AsyncSession, access: ProjectAccess, name: str, version: int | str
) -> ContextSnapshot:
    parsed = service.parse_version(version)
    snapshot = await service.get_snapshot(session, access.project_id, name, parsed)
    if snapshot is None:
        if parsed in (None, "latest"):
            raise not_found(NOT_FOUND)
        raise not_found(f"Version {parsed} du snapshot « {name.strip().lower()} » introuvable")
    return snapshot


@router.get("", response_model=list[SnapshotGroup], summary="Snapshots du projet")
async def list_snapshots(access: ViewerAccess, session: SessionDep) -> list[SnapshotGroup]:
    return await service.list_groups(session, access.project_id)


@router.get("/{name}", response_model=list[SnapshotSummary], summary="Versions d'un snapshot")
async def list_snapshot_versions(
    name: str, access: ViewerAccess, session: SessionDep
) -> list[SnapshotSummary]:
    versions = await service.list_versions(session, access.project_id, name)
    if not versions:
        raise not_found(NOT_FOUND)
    return await service.summaries(session, versions)


@router.get("/{name}/diff", response_model=SnapshotDiff, summary="Différences entre deux versions")
async def diff_snapshot(
    name: str,
    access: ViewerAccess,
    session: SessionDep,
    from_: int = Query(..., alias="from", ge=1),
    to: int = Query(..., ge=1),
) -> SnapshotDiff:
    if from_ == to:
        raise validation_error("Choisissez deux versions différentes à comparer")
    old = await _load(session, access, name, from_)
    new = await _load(session, access, name, to)
    return await service.present_diff(session, old, new, Viewer.from_access(access))


@router.get("/{name}/{version}", response_model=Snapshot, summary="Une version (« latest » accepté)")
async def get_snapshot(name: str, version: str, access: AgentViewerAccess, session: SessionDep) -> Snapshot:
    snapshot = await _load(session, access, name, version)
    return await service.present(session, snapshot, Viewer.from_access(access))
