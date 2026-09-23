"""Context snapshots (STUB — implemented by the context teammate). See ``app.context.snapshots``.

Route order matters: ``/{name}/diff`` is declared before ``/{name}/{version}``.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import AgentViewerAccess, SessionDep, ViewerAccess
from app.schemas import Snapshot, SnapshotDiff, SnapshotGroup, SnapshotSummary

router = APIRouter(prefix="/projects/{slug}/snapshots", tags=["snapshots"])


@router.get("", response_model=list[SnapshotGroup], summary="Snapshots du projet")
async def list_snapshots(access: ViewerAccess, session: SessionDep) -> list[SnapshotGroup]:
    raise NotImplementedError


@router.get("/{name}", response_model=list[SnapshotSummary], summary="Versions d'un snapshot")
async def list_snapshot_versions(
    name: str, access: ViewerAccess, session: SessionDep
) -> list[SnapshotSummary]:
    raise NotImplementedError


@router.get("/{name}/diff", response_model=SnapshotDiff, summary="Différences entre deux versions")
async def diff_snapshot(
    name: str,
    access: ViewerAccess,
    session: SessionDep,
    from_: int = Query(..., alias="from", ge=1),
    to: int = Query(..., ge=1),
) -> SnapshotDiff:
    raise NotImplementedError


@router.get("/{name}/{version}", response_model=Snapshot, summary="Une version (« latest » accepté)")
async def get_snapshot(name: str, version: str, access: AgentViewerAccess, session: SessionDep) -> Snapshot:
    raise NotImplementedError
