"""OpenSearch access: client, index management, indexing and raw BM25 / k-NN queries.

Client and index names are implemented here; mappings, indexing and search functions are the
retrieval teammate's contract (ARCHITECTURE §6):

* indices ``{ORBIT_INDEX_PREFIX}-chunks-v1`` and ``{ORBIT_INDEX_PREFIX}-memory-v1`` with
  ``index.knn: true`` and the custom ``french`` analyzer (elision + lowercase + asciifolding +
  french_stop + french_stemmer);
* common fields: ``id``, ``project_id``, ``text``, ``title`` (boost 2), ``embedding`` (knn_vector,
  dim ``ORBIT_EMBEDDING_DIM``, hnsw, cosinesimil, engine lucene), ``classification``,
  ``acl_principals``, ``status``, ``tags``, ``created_at``, ``source_updated_at``; chunks add
  ``document_id``, ``version``, ``source_kind``, ``section``; memory adds ``lineage_id``, ``scope``,
  ``kind``, ``subject_user_id``, ``session_id``, ``valid_to``, ``expires_at``;
* retrieval pre-filters on **project only** (plus organisation long-term memory, ``project_id``
  absent); governance is applied afterwards so that every exclusion can be explained;
* superseded chunks stay indexed (status updated); forgotten content is deleted from the index.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from opensearchpy import AsyncOpenSearch

from app.config import settings

IndexKind = Literal["chunks", "memory"]

_client: AsyncOpenSearch | None = None


@dataclass(slots=True)
class OSHit:
    """One raw hit returned by :func:`bm25_search` / :func:`knn_search`."""

    id: str
    score: float
    source: dict[str, Any] = field(default_factory=dict)


def index_name(kind: IndexKind) -> str:
    return settings.chunks_index if kind == "chunks" else settings.memory_index


def get_client() -> AsyncOpenSearch:
    """Process-wide async client (``ORBIT_OPENSEARCH_URL``, security plugin disabled locally)."""
    global _client
    if _client is None:
        _client = AsyncOpenSearch(
            hosts=[settings.opensearch_url],
            timeout=30,
            max_retries=2,
            retry_on_timeout=True,
            http_compress=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
    _client = None


async def ping() -> dict[str, Any]:
    """Cluster health (used by ``/ready``)."""
    health = await get_client().cluster.health()
    return {"status": health.get("status"), "nodes": health.get("number_of_nodes")}


async def ensure_indices() -> None:
    """Create both indices with their settings/mappings when missing; validate the vector dimension
    of existing ones (raise ``RuntimeError`` on mismatch). Idempotent; called at API/worker startup."""
    raise NotImplementedError("Création des index OpenSearch non implémentée")


async def index_chunks(docs: Sequence[Mapping[str, Any]], *, refresh: bool = False) -> int:
    """Bulk upsert chunk documents (``_id`` = chunk id, fields per module docstring). Returns the count."""
    raise NotImplementedError


async def index_memory(items: Sequence[Mapping[str, Any]], *, refresh: bool = False) -> int:
    """Bulk upsert memory item documents (``_id`` = memory item id). Returns the count."""
    raise NotImplementedError


async def update_status(kind: IndexKind, ids: Sequence[str], status: str, *, refresh: bool = False) -> int:
    """Set ``status`` on the given documents (e.g. chunks ``superseded``). Returns updated count."""
    raise NotImplementedError


async def update_fields(
    kind: IndexKind, ids: Sequence[str], fields: Mapping[str, Any], *, refresh: bool = False
) -> int:
    """Partial update of metadata fields (classification, acl_principals, tags…) on documents."""
    raise NotImplementedError


async def delete_by_ids(kind: IndexKind, ids: Sequence[str], *, refresh: bool = False) -> int:
    """Delete documents (selective forgetting). Returns deleted count."""
    raise NotImplementedError


async def bm25_search(
    kind: IndexKind,
    query: str,
    *,
    project_id: str,
    size: int = 40,
    filters: Sequence[Mapping[str, Any]] | None = None,
    include_org_memory: bool = True,
) -> list[OSHit]:
    """BM25 ``multi_match`` on ``title^2`` + ``text`` (french analyzer), filtered by project."""
    raise NotImplementedError


async def knn_search(
    kind: IndexKind,
    vector: Sequence[float],
    *,
    project_id: str,
    size: int = 40,
    filters: Sequence[Mapping[str, Any]] | None = None,
    include_org_memory: bool = True,
) -> list[OSHit]:
    """k-NN (lucene hnsw, cosine) on ``embedding`` with a project pre-filter."""
    raise NotImplementedError
