"""Hybrid search over chunks (STUB — implemented by the retrieval teammate).

Results are filtered by the caller's ACL principals and clearance.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import SessionDep, ViewerAccess
from app.schemas import SearchHit

router = APIRouter(prefix="/projects/{slug}/search", tags=["search"])


@router.get("", response_model=list[SearchHit], summary="Recherche hybride (BM25 + k-NN), filtrée par droits")
async def search(
    access: ViewerAccess,
    session: SessionDep,
    q: str = Query(..., min_length=1, max_length=1000),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SearchHit]:
    raise NotImplementedError
