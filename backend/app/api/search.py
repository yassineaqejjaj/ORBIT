"""Hybrid search over chunks (BM25 + k-NN fused with RRF), filtered by the caller's rights.

Rights are enforced twice: as OpenSearch pre-filters (active chunks, classification ≤ clearance, ACL
principals) and again against Postgres (document forgotten, ACL or classification changed since
indexing). Callers below ``editor`` and agents receive the PII-redacted text.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import SessionDep, ViewerAccess
from app.enums import ChunkStatus, DocumentStatus
from app.errors import ApiError, validation_error
from app.ingestion.service import DocumentViewer
from app.models import Chunk, Document, Source
from app.schemas import SearchHit
from app.search.hybrid import hybrid_search

logger = logging.getLogger("orbit.api.search")

router = APIRouter(prefix="/projects/{slug}/search", tags=["search"])

MIN_CANDIDATES = 40


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


@router.get("", response_model=list[SearchHit], summary="Recherche hybride (BM25 + k-NN), filtrée par droits")
async def search(
    access: ViewerAccess,
    session: SessionDep,
    q: str = Query(..., min_length=1, max_length=1000),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SearchHit]:
    query = q.strip()
    if not query:
        raise validation_error("La requête de recherche est vide")
    viewer = DocumentViewer.from_access(access)
    try:
        fused = await hybrid_search(
            "chunks",
            query,
            None,
            project_id=access.project_id,
            size_each=max(MIN_CANDIDATES, limit * 3),
            filters=viewer.search_filters(),
            include_embedding=False,
        )
    except Exception as exc:
        logger.warning("Hybrid search failed for project %s: %s", access.project_id, exc)
        raise ApiError(
            503, "Moteur de recherche indisponible, réessayez dans un instant", code="service_unavailable"
        ) from exc

    ids = [cid for hit in fused if (cid := _uuid_or_none(hit.id)) is not None]
    if not ids:
        return []
    rows = await session.execute(
        select(Chunk, Document, Source.kind)
        .join(Document, Document.id == Chunk.document_id)
        .outerjoin(Source, Source.id == Document.source_id)
        .where(Chunk.id.in_(ids), Chunk.project_id == access.project_id)
    )
    by_id = {chunk.id: (chunk, document, kind) for chunk, document, kind in rows.tuples()}

    results: list[SearchHit] = []
    for hit in fused:
        entry = by_id.get(_uuid_or_none(hit.id))  # type: ignore[arg-type]
        if entry is None:
            continue  # stale index entry (chunk deleted)
        chunk, document, kind = entry
        if (
            chunk.status != ChunkStatus.active
            or chunk.quarantined  # §A1: never served while in quarantine
            or document.status == DocumentStatus.forgotten
            or chunk.version != document.current_version
            or not viewer.can_view(document)
            or not viewer.allows(chunk.acl_principals, int(chunk.classification))
        ):
            continue
        results.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title,
                source_kind=kind,
                text=chunk.text if viewer.can_see_pii else chunk.text_redacted,
                score=round(float(hit.rrf_norm), 4),
                bm25=round(hit.bm25_score, 4) if hit.bm25_score is not None else None,
                dense=round(hit.dense_score, 4) if hit.dense_score is not None else None,
                section=chunk.section,
                source_updated_at=document.source_updated_at,
            )
        )
        if len(results) >= limit:
            break
    return results
