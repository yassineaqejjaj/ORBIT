"""OpenSearch access: client, index management, indexing and raw BM25 / k-NN queries.

ARCHITECTURE §6:

* indices ``{ORBIT_INDEX_PREFIX}-chunks-v1`` and ``{ORBIT_INDEX_PREFIX}-memory-v1`` with
  ``index.knn: true`` and the custom ``french`` analyzer (elision + lowercase + asciifolding +
  french_stop + french_stemmer);
* common fields: ``id``, ``project_id``, ``text``, ``title`` (boost 2), ``embedding`` (knn_vector,
  dim ``ORBIT_EMBEDDING_DIM``, hnsw, cosinesimil, engine lucene), ``classification``,
  ``acl_principals``, ``status``, ``tags``, ``created_at``, ``source_updated_at``; chunks add
  ``document_id``, ``version``, ``source_kind``, ``section``; memory adds ``lineage_id``, ``scope``,
  ``kind``, ``subject_user_id``, ``session_id``, ``valid_to``, ``expires_at``. A few stored-only /
  auxiliary fields complete them (``text_redacted``, ``ordinal``, ``is_current``, ``confidence``…);
* retrieval pre-filters on **project only** (plus organisation long-term memory, ``project_id``
  absent); governance is applied afterwards so that every exclusion can be explained;
* superseded chunks stay indexed (status updated); forgotten content is deleted from the index.

Scores: :func:`bm25_search` returns raw BM25 scores; :func:`knn_search` returns the **cosine
similarity** (converted from the lucene ``(1 + cos) / 2`` score).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from opensearchpy import AsyncOpenSearch
from opensearchpy.exceptions import NotFoundError, RequestError, TransportError

from app.config import settings

logger = logging.getLogger("orbit.opensearch")

IndexKind = Literal["chunks", "memory"]
INDEX_KINDS: tuple[IndexKind, ...] = ("chunks", "memory")

BULK_BATCH_SIZE = 500
_SOURCE_EXCLUDES = ["embedding"]

_client: AsyncOpenSearch | None = None


class IndexConfigurationError(RuntimeError):
    """An existing index is incompatible with the configuration (e.g. vector dimension)."""


class IndexingError(RuntimeError):
    """A bulk operation reported item failures."""


@dataclass(slots=True)
class OSHit:
    """One hit returned by :func:`bm25_search` / :func:`knn_search`."""

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


# --- Settings & mappings (ARCHITECTURE §6) ---------------------------------------------------------------

FRENCH_ELISION_ARTICLES = [
    "l", "m", "t", "qu", "n", "s", "j", "d", "c", "jusqu", "quoiqu", "lorsqu", "puisqu",
]  # fmt: skip


def index_settings() -> dict[str, Any]:
    return {
        "index": {
            "knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "1s",
        },
        "analysis": {
            "filter": {
                "french_elision": {
                    "type": "elision",
                    "articles_case": True,
                    "articles": FRENCH_ELISION_ARTICLES,
                },
                "french_stop": {"type": "stop", "stopwords": "_french_"},
                "french_stemmer": {"type": "stemmer", "language": "light_french"},
            },
            "analyzer": {
                "french": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["french_elision", "lowercase", "asciifolding", "french_stop", "french_stemmer"],
                }
            },
        },
    }


def _embedding_field() -> dict[str, Any]:
    return {
        "type": "knn_vector",
        "dimension": settings.embedding_dim,
        "method": {
            "name": "hnsw",
            "space_type": "cosinesimil",
            "engine": "lucene",
            "parameters": {"ef_construction": 128, "m": 16},
        },
    }


def _common_properties() -> dict[str, Any]:
    return {
        "id": {"type": "keyword"},
        "project_id": {"type": "keyword"},
        "text": {"type": "text", "analyzer": "french"},
        "text_redacted": {"type": "text", "index": False},
        "title": {
            "type": "text",
            "analyzer": "french",
            "fields": {"raw": {"type": "keyword", "ignore_above": 512}},
        },
        "embedding": _embedding_field(),
        "classification": {"type": "integer"},
        "acl_principals": {"type": "keyword"},
        "status": {"type": "keyword"},
        "tags": {"type": "keyword"},
        "created_at": {"type": "date"},
        "source_updated_at": {"type": "date"},
    }


def chunk_mapping() -> dict[str, Any]:
    properties = _common_properties()
    properties.update(
        {
            "document_id": {"type": "keyword"},
            "version": {"type": "integer"},
            "source_kind": {"type": "keyword"},
            "section": {"type": "text", "analyzer": "french", "fields": {"raw": {"type": "keyword"}}},
            "source_id": {"type": "keyword"},
            "ordinal": {"type": "integer"},
            "token_count": {"type": "integer"},
            "char_start": {"type": "integer", "index": False},
            "char_end": {"type": "integer", "index": False},
            "pii_count": {"type": "integer"},
            "uri": {"type": "keyword", "index": False},
            "mime_type": {"type": "keyword"},
        }
    )
    return {"dynamic": False, "properties": properties}


def memory_mapping() -> dict[str, Any]:
    properties = _common_properties()
    properties.update(
        {
            "lineage_id": {"type": "keyword"},
            "version": {"type": "integer"},
            "is_current": {"type": "boolean"},
            "scope": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "subject_user_id": {"type": "keyword"},
            "session_id": {"type": "keyword"},
            "valid_from": {"type": "date"},
            "valid_to": {"type": "date"},
            "expires_at": {"type": "date"},
            "confidence": {"type": "float"},
            "supersedes_id": {"type": "keyword"},
            "superseded_by_id": {"type": "keyword"},
            "created_by_type": {"type": "keyword"},
        }
    )
    return {"dynamic": False, "properties": properties}


def mapping_for(kind: IndexKind) -> dict[str, Any]:
    return chunk_mapping() if kind == "chunks" else memory_mapping()


async def ensure_indices() -> None:
    """Create both indices with their settings/mappings when missing; validate the vector dimension
    of existing ones (log a clear error and raise ``IndexConfigurationError`` on mismatch) and add
    fields introduced since their creation. Idempotent; called at API/worker startup.

    Also warms up and validates the embedding model (dimension check) so the first ingestion or
    context request does not pay the model loading time.
    """
    client = get_client()
    errors: list[str] = []
    for kind in INDEX_KINDS:
        name = index_name(kind)
        mapping = mapping_for(kind)
        if not await client.indices.exists(index=name):
            try:
                await client.indices.create(index=name, body={"settings": index_settings(), "mappings": mapping})
                logger.info("OpenSearch index %s created (dim=%d)", name, settings.embedding_dim)
                continue
            except RequestError as exc:
                if "resource_already_exists_exception" not in str(exc):
                    raise
                logger.info("OpenSearch index %s created concurrently by another process", name)
        try:
            await _validate_existing(name, mapping)
        except IndexConfigurationError as exc:
            logger.error("%s", exc)
            errors.append(str(exc))
    await _warm_up_embedder()
    if errors:
        raise IndexConfigurationError(" ; ".join(errors))


async def _validate_existing(name: str, expected: Mapping[str, Any]) -> None:
    client = get_client()
    current = await client.indices.get_mapping(index=name)
    properties: dict[str, Any] = {}
    for body in current.values():
        properties = body.get("mappings", {}).get("properties", {})
        break
    embedding = properties.get("embedding", {})
    dimension = embedding.get("dimension")
    if dimension is not None and int(dimension) != settings.embedding_dim:
        raise IndexConfigurationError(
            f"Index OpenSearch « {name} » : dimension des vecteurs {dimension} ≠ ORBIT_EMBEDDING_DIM="
            f"{settings.embedding_dim}. Supprimez l'index (ou changez ORBIT_INDEX_PREFIX) puis "
            "relancez l'ingestion, ou revenez au modèle d'embeddings d'origine."
        )
    missing = {key: value for key, value in expected["properties"].items() if key not in properties}
    if missing:
        try:
            await client.indices.put_mapping(index=name, body={"properties": missing})
            logger.info("OpenSearch index %s: added fields %s", name, ", ".join(sorted(missing)))
        except TransportError as exc:
            logger.warning("OpenSearch index %s: unable to add fields %s: %s", name, sorted(missing), exc)


async def _warm_up_embedder() -> None:
    from app.search.embeddings import check_embedder

    try:
        info = await check_embedder()
        logger.info("Embedding model validated: %s", info)
    except Exception as exc:  # the API must start even if the model is unavailable (/ready reports it)
        logger.error("Embedding model check failed: %s", exc)


async def delete_indices() -> None:
    """Drop both indices (tests / reset). Missing indices are ignored."""
    client = get_client()
    for kind in INDEX_KINDS:
        await client.indices.delete(index=index_name(kind), ignore_unavailable=True)


async def refresh(kind: IndexKind | None = None) -> None:
    kinds = [kind] if kind else list(INDEX_KINDS)
    await get_client().indices.refresh(index=",".join(index_name(k) for k in kinds))


# --- Serialisation --------------------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):  # numpy arrays / scalars
        return value.tolist()
    return str(value)


def _refresh_param(refresh_now: bool) -> str | bool:
    return "wait_for" if refresh_now else False


# --- Bulk operations -------------------------------------------------------------------------------------


async def _bulk(
    kind: IndexKind,
    actions: list[tuple[dict[str, Any], dict[str, Any] | None]],
    *,
    refresh: bool,
    ignore_missing: bool = False,
) -> int:
    """Run bulk ``actions`` (``(action_meta, body_or_None)``) in batches. Returns the success count."""
    if not actions:
        return 0
    client = get_client()
    succeeded = 0
    failures: list[str] = []
    total_batches = (len(actions) + BULK_BATCH_SIZE - 1) // BULK_BATCH_SIZE
    for batch_index in range(total_batches):
        batch = actions[batch_index * BULK_BATCH_SIZE : (batch_index + 1) * BULK_BATCH_SIZE]
        lines: list[dict[str, Any]] = []
        for meta, body in batch:
            lines.append(meta)
            if body is not None:
                lines.append(body)
        is_last = batch_index == total_batches - 1
        response = await client.bulk(
            body=lines, index=index_name(kind), refresh=_refresh_param(refresh and is_last)
        )
        for item in response.get("items", []):
            (op, result), *_ = item.items()
            status = int(result.get("status", 500))
            if status < 300:
                succeeded += 1
            elif status == 404 and ignore_missing:
                continue
            else:
                error = result.get("error") or {}
                reason = error.get("reason") if isinstance(error, dict) else str(error)
                failures.append(f"{op} {result.get('_id')}: {reason or status}")
    if failures:
        raise IndexingError(
            f"{len(failures)} opération(s) OpenSearch en échec sur {index_name(kind)} : " + "; ".join(failures[:3])
        )
    return succeeded


def _prepare_doc(doc: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    body = _jsonable(dict(doc))
    doc_id = body.get("id")
    if not doc_id:
        raise ValueError("Chaque document indexé doit avoir un champ « id »")
    embedding = body.get("embedding")
    if embedding is not None and len(embedding) != settings.embedding_dim:
        raise IndexingError(
            f"Vecteur de dimension {len(embedding)} pour « {doc_id} » (attendu : {settings.embedding_dim})"
        )
    return str(doc_id), body


async def _index_docs(kind: IndexKind, docs: Sequence[Mapping[str, Any]], *, refresh: bool) -> int:
    actions: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for doc in docs:
        doc_id, body = _prepare_doc(doc)
        actions.append(({"index": {"_index": index_name(kind), "_id": doc_id}}, body))
    return await _bulk(kind, actions, refresh=refresh)


async def index_chunks(docs: Sequence[Mapping[str, Any]], *, refresh: bool = False) -> int:
    """Bulk upsert chunk documents (``_id`` = chunk id, fields per module docstring). Returns the count."""
    return await _index_docs("chunks", docs, refresh=refresh)


async def index_memory(items: Sequence[Mapping[str, Any]], *, refresh: bool = False) -> int:
    """Bulk upsert memory item documents (``_id`` = memory item id). Returns the count."""
    return await _index_docs("memory", items, refresh=refresh)


async def update_fields(
    kind: IndexKind, ids: Sequence[str], fields: Mapping[str, Any], *, refresh: bool = False
) -> int:
    """Partial update of metadata fields (classification, acl_principals, tags…) on documents.

    Missing documents are ignored. Returns the updated count.
    """
    if not ids or not fields:
        return 0
    body = {"doc": _jsonable(dict(fields))}
    actions: list[tuple[dict[str, Any], dict[str, Any] | None]] = [
        ({"update": {"_index": index_name(kind), "_id": str(doc_id), "retry_on_conflict": 3}}, body)
        for doc_id in dict.fromkeys(str(i) for i in ids)
    ]
    return await _bulk(kind, actions, refresh=refresh, ignore_missing=True)


async def update_status(kind: IndexKind, ids: Sequence[str], status: str, *, refresh: bool = False) -> int:
    """Set ``status`` on the given documents (e.g. chunks ``superseded``). Returns updated count."""
    return await update_fields(kind, ids, {"status": _jsonable(status)}, refresh=refresh)


async def delete_by_ids(kind: IndexKind, ids: Sequence[str], *, refresh: bool = False) -> int:
    """Delete documents (selective forgetting). Missing ids are ignored. Returns deleted count."""
    if not ids:
        return 0
    actions: list[tuple[dict[str, Any], dict[str, Any] | None]] = [
        ({"delete": {"_index": index_name(kind), "_id": str(doc_id)}}, None)
        for doc_id in dict.fromkeys(str(i) for i in ids)
    ]
    return await _bulk(kind, actions, refresh=refresh, ignore_missing=True)


async def delete_by_query(kind: IndexKind, query: Mapping[str, Any], *, refresh: bool = False) -> int:
    """Delete every document matching ``query`` (e.g. all chunks of a forgotten document)."""
    response = await get_client().delete_by_query(
        index=index_name(kind),
        body={"query": _jsonable(dict(query))},
        refresh=refresh,
        conflicts="proceed",
    )
    return int(response.get("deleted", 0))


async def update_by_query(
    kind: IndexKind, query: Mapping[str, Any], fields: Mapping[str, Any], *, refresh: bool = False
) -> int:
    """Set ``fields`` (scalars / lists) on every document matching ``query``. Returns updated count."""
    if not fields:
        return 0
    assignments = []
    params: dict[str, Any] = {}
    for index, (key, value) in enumerate(fields.items()):
        assignments.append(f"ctx._source['{key}'] = params.p{index};")
        params[f"p{index}"] = _jsonable(value)
    response = await get_client().update_by_query(
        index=index_name(kind),
        body={
            "query": _jsonable(dict(query)),
            "script": {"source": " ".join(assignments), "lang": "painless", "params": params},
        },
        refresh=refresh,
        conflicts="proceed",
    )
    return int(response.get("updated", 0))


async def get_documents(
    kind: IndexKind, ids: Sequence[str], *, include_embedding: bool = False
) -> dict[str, dict[str, Any]]:
    """Fetch indexed documents by id (``{id: source}``; missing ids are absent)."""
    unique_ids = list(dict.fromkeys(str(i) for i in ids))
    if not unique_ids:
        return {}
    kwargs: dict[str, Any] = {}
    if not include_embedding:
        kwargs["_source_excludes"] = _SOURCE_EXCLUDES
    response = await get_client().mget(index=index_name(kind), body={"ids": unique_ids}, **kwargs)
    return {doc["_id"]: doc.get("_source", {}) for doc in response.get("docs", []) if doc.get("found")}


async def count(
    kind: IndexKind,
    *,
    project_id: str | uuid.UUID | None = None,
    filters: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
) -> int:
    """Count indexed documents (optionally for one project and extra filters)."""
    clauses: list[dict[str, Any]] = []
    if project_id is not None:
        clauses.append({"term": {"project_id": str(project_id)}})
    clauses.extend(normalize_filters(filters))
    query: dict[str, Any] = {"bool": {"filter": clauses}} if clauses else {"match_all": {}}
    try:
        response = await get_client().count(index=index_name(kind), body={"query": query})
    except NotFoundError:
        return 0
    return int(response.get("count", 0))


async def count_by_project(kind: IndexKind, project_ids: Iterable[str | uuid.UUID]) -> dict[str, int]:
    """``{project_id: indexed document count}`` (terms aggregation, active chunks / current memory)."""
    ids = [str(pid) for pid in project_ids]
    if not ids:
        return {}
    status_filter = {"term": {"status": "active"}} if kind == "chunks" else {"term": {"is_current": True}}
    body = {
        "size": 0,
        "query": {"bool": {"filter": [{"terms": {"project_id": ids}}, status_filter]}},
        "aggs": {"by_project": {"terms": {"field": "project_id", "size": max(10, len(ids))}}},
    }
    try:
        response = await get_client().search(index=index_name(kind), body=body)
    except NotFoundError:
        return dict.fromkeys(ids, 0)
    buckets = response.get("aggregations", {}).get("by_project", {}).get("buckets", [])
    counts = dict.fromkeys(ids, 0)
    for bucket in buckets:
        counts[str(bucket["key"])] = int(bucket["doc_count"])
    return counts


# --- Queries ---------------------------------------------------------------------------------------------


def normalize_filters(filters: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Turn ``filters`` into OpenSearch filter clauses.

    * a sequence is taken as ready-made clauses (``[{"term": {...}}, {"range": {...}}]``);
    * a mapping ``{field: value}`` becomes ``term`` (scalar), ``terms`` (list/tuple/set) or ``range``
      (dict with ``gt``/``gte``/``lt``/``lte``). ``None`` values are ignored.
    """
    if not filters:
        return []
    if not isinstance(filters, Mapping):
        return [_jsonable(dict(clause)) for clause in filters]
    clauses: list[dict[str, Any]] = []
    for key, value in filters.items():
        if value is None:
            continue
        if isinstance(value, Mapping):
            clauses.append({"range": {key: _jsonable(dict(value))}})
        elif isinstance(value, list | tuple | set | frozenset):
            values = [_jsonable(v) for v in value]
            clauses.append({"terms": {key: values}})
        else:
            clauses.append({"term": {key: _jsonable(value)}})
    return clauses


def scope_filter(kind: IndexKind, project_id: str | uuid.UUID, include_org_memory: bool) -> dict[str, Any]:
    """Project pre-filter; for memory, organisation long-term items (no ``project_id``) are included."""
    project_term = {"term": {"project_id": str(project_id)}}
    if kind == "memory" and include_org_memory:
        return {
            "bool": {
                "should": [project_term, {"bool": {"must_not": {"exists": {"field": "project_id"}}}}],
                "minimum_should_match": 1,
            }
        }
    return project_term


def build_filter(
    kind: IndexKind,
    project_id: str | uuid.UUID,
    filters: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    include_org_memory: bool,
) -> dict[str, Any]:
    return {"bool": {"filter": [scope_filter(kind, project_id, include_org_memory), *normalize_filters(filters)]}}


def _hits(response: Mapping[str, Any], *, cosine: bool = False) -> list[OSHit]:
    results: list[OSHit] = []
    for hit in response.get("hits", {}).get("hits", []):
        raw = float(hit.get("_score") or 0.0)
        score = max(0.0, min(1.0, 2.0 * raw - 1.0)) if cosine else raw
        source = dict(hit.get("_source") or {})
        source.pop("embedding", None)
        results.append(OSHit(id=str(hit["_id"]), score=score, source=source))
    return results


async def bm25_search(
    kind: IndexKind,
    query: str,
    *,
    project_id: str | uuid.UUID,
    size: int = 40,
    filters: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    include_org_memory: bool = True,
) -> list[OSHit]:
    """BM25 ``multi_match`` on ``title^2`` + ``text`` (french analyzer), filtered by project."""
    text = (query or "").strip()
    if not text or size <= 0:
        return []
    body = {
        "size": size,
        "_source": {"excludes": _SOURCE_EXCLUDES},
        "query": {
            "bool": {
                "must": {
                    "multi_match": {
                        "query": text[:4000],
                        "fields": ["title^2", "text"],
                        "type": "best_fields",
                        "tie_breaker": 0.3,
                        "analyzer": "french",
                    }
                },
                "filter": build_filter(kind, project_id, filters, include_org_memory)["bool"]["filter"],
            }
        },
    }
    try:
        response = await get_client().search(index=index_name(kind), body=body)
    except NotFoundError:
        logger.warning("OpenSearch index %s missing: BM25 search returns no result", index_name(kind))
        return []
    return _hits(response)


async def knn_search(
    kind: IndexKind,
    vector: Sequence[float],
    *,
    project_id: str | uuid.UUID,
    size: int = 40,
    filters: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    include_org_memory: bool = True,
) -> list[OSHit]:
    """k-NN (lucene hnsw, cosine) on ``embedding`` with an efficient project pre-filter.

    ``OSHit.score`` is the cosine similarity clamped to ``[0, 1]``.
    """
    if not vector or size <= 0:
        return []
    if len(vector) != settings.embedding_dim:
        raise ValueError(f"Vecteur de requête de dimension {len(vector)} (attendu : {settings.embedding_dim})")
    body = {
        "size": size,
        "_source": {"excludes": _SOURCE_EXCLUDES},
        "query": {
            "knn": {
                "embedding": {
                    "vector": [float(v) for v in vector],
                    "k": size,
                    "filter": build_filter(kind, project_id, filters, include_org_memory),
                }
            }
        },
    }
    try:
        response = await get_client().search(index=index_name(kind), body=body)
    except NotFoundError:
        logger.warning("OpenSearch index %s missing: k-NN search returns no result", index_name(kind))
        return []
    return _hits(response, cosine=True)
