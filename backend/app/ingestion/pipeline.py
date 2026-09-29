"""Job dispatcher and ingestion pipeline (ARCHITECTURE §7).

``run_job`` is called by the worker (``app.worker``) inside its own session with a job already
claimed (``running``). Handlers:

* ``ingest``: extract → pii → classify → chunk → embed → index → extract_memory, each step timed via
  :func:`app.ingestion.queue.track_step` (``job.steps`` feeds the Sources screen). The document goes
  ``processing`` → ``indexed`` / ``failed`` (``status_reason`` in French); ``pii_count``,
  classification (raised, never lowered), ``source.last_ingested_at`` are updated; chunks of the
  version are upserted with deterministic ids (retries and reprocessing keep chunk ids, hence
  memory provenance links); older versions' chunks become ``superseded`` in Postgres and in the
  index, with a ``supersedes`` relation; an ``extract_memory`` job is chained.
* ``reindex``: re-sync index metadata (``mode="metadata"``) or re-embed and re-index every chunk
  (``mode="full"``, e.g. after an embedding model change) of one document or of the whole project.
* ``forget``: tombstone propagation — chunks deleted from the index, ``[oublié]`` in Postgres, raw
  files purged, derived memory handled by ``app.memory.lifecycle.propagate_document_forget``.
* ``extract_memory`` / ``consolidate``: delegated to ``app.memory.extractor.extract_from_document``
  and ``app.memory.consolidation.run_consolidation`` (imported lazily).

Handlers raise :class:`~app.ingestion.queue.PermanentJobError` for non-retryable failures; any
other exception is retried by the worker. They never call ``mark_succeeded``/``mark_failed`` and do
not commit the final state (the worker does); intermediate commits record progress.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.enums import (
    PII_LABELS,
    ActorType,
    ChunkStatus,
    DocumentStatus,
    JobKind,
    RelationNodeType,
    RelationType,
    TombstoneTarget,
    classification_code,
    classification_label,
)
from app.ingestion import classifier
from app.ingestion.chunker import chunk_text
from app.ingestion.extractors import ExtractedDocument, ExtractionError, extract, extract_text_content
from app.ingestion.pii import PiiEntity, analyze, entities_in_span, redact
from app.ingestion.queue import PermanentJobError, enqueue_job, track_step
from app.models import Chunk, Document, DocumentVersion, IngestionJob, Relation, Source, Tombstone
from app.search import opensearch
from app.search.embeddings import EmbeddingDimensionError, EmbeddingError, aget_embedder
from app.search.opensearch import IndexingError
from app.services import audit
from app.services.audit import Actor, AuditAction
from app.storage.object_store import ObjectNotFoundError, ObjectStoreError, get_object_store

logger = logging.getLogger("orbit.pipeline")

FORGOTTEN_TEXT = "[oublié]"
#: Namespace of deterministic chunk ids: ``uuid5(ns, "<document_id>:<version>:<ordinal>")``.
CHUNK_ID_NAMESPACE = uuid.UUID("5f0c2a4e-8d1b-4c7e-9a36-0b7f3e2d9c41")
EMBED_BATCH = 64

FORMAT_LABELS = {
    "pdf": "PDF",
    "docx": "Word (DOCX)",
    "markdown": "Markdown",
    "text": "texte brut",
    "html": "HTML",
    "json": "JSON",
    "csv": "CSV",
}


def chunk_uuid(document_id: uuid.UUID, version: int, ordinal: int) -> uuid.UUID:
    return uuid.uuid5(CHUNK_ID_NAMESPACE, f"{document_id}:{version}:{ordinal}")


async def run_job(session: AsyncSession, job: IngestionJob) -> None:
    """Dispatch ``job`` to the handler of ``job.kind``."""
    handlers = {
        JobKind.ingest: handle_ingest,
        JobKind.reindex: handle_reindex,
        JobKind.forget: handle_forget,
        JobKind.consolidate: handle_consolidate,
        JobKind.extract_memory: handle_extract_memory,
    }
    await handlers[JobKind(job.kind)](session, job)


# --- Helpers --------------------------------------------------------------------------------------


def actor_from_payload(payload: dict[str, Any] | None) -> Actor:
    """Rebuild the audit actor stored in a job payload (``{"actor": {"type", "id", "label"}}``)."""
    data = (payload or {}).get("actor")
    if isinstance(data, dict):
        try:
            actor_id = uuid.UUID(str(data["id"])) if data.get("id") else None
            return Actor(ActorType(data.get("type", "system")), actor_id, str(data.get("label") or ""))
        except (ValueError, KeyError):
            pass
    return Actor.system()


def actor_payload(actor: Actor) -> dict[str, Any]:
    return {"type": actor.type.value, "id": str(actor.id) if actor.id else None, "label": actor.label}


def pii_summary(entities: Sequence[PiiEntity]) -> str:
    if not entities:
        return "aucune donnée personnelle détectée"
    counts = Counter(e.type for e in entities)
    parts = [f"{PII_LABELS[t].strip('[]').capitalize()} ×{n}" for t, n in counts.most_common()]
    noun = "entité" if len(entities) == 1 else "entités"
    return f"{len(entities)} {noun} : {', '.join(parts)}"


def embedding_input(title: str, section: str | None, text: str) -> str:
    """Text embedded for a chunk: document title and section give context to short passages."""
    header = title if not section else f"{title} — {section}"
    return f"{header}\n{text}"


def chunk_index_doc(
    chunk: Chunk, document: Document, source: Source | None, embedding: Sequence[float]
) -> dict[str, Any]:
    """OpenSearch document of a chunk (ARCHITECTURE §6)."""
    return {
        "id": str(chunk.id),
        "project_id": str(chunk.project_id),
        "document_id": str(chunk.document_id),
        "source_id": str(document.source_id),
        "version": chunk.version,
        "ordinal": chunk.ordinal,
        "title": document.title,
        "text": chunk.text,
        "text_redacted": chunk.text_redacted,
        "section": chunk.section,
        "embedding": list(embedding),
        "classification": int(chunk.classification),
        "acl_principals": list(chunk.acl_principals),
        "status": ChunkStatus(chunk.status).value,
        "tags": list(document.tags or []),
        "source_kind": source.kind.value if source is not None else None,
        "created_at": chunk.created_at or utcnow(),
        "source_updated_at": document.source_updated_at,
        "token_count": chunk.token_count,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "pii_count": len(chunk.pii or []),
        "uri": document.uri,
        "mime_type": document.mime_type,
    }


def document_index_fields(document: Document, source: Source | None) -> dict[str, Any]:
    """Document-level metadata replicated on every chunk of the index."""
    return {
        "title": document.title,
        "classification": int(document.classification),
        "acl_principals": list(document.acl_principals),
        "tags": list(document.tags or []),
        "source_kind": source.kind.value if source is not None else None,
        "source_updated_at": document.source_updated_at,
        "uri": document.uri,
    }


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    embedder = await aget_embedder()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors.extend(await embedder.embed_documents(list(texts[start : start + EMBED_BATCH])))
    if len(vectors) != len(texts):
        raise RuntimeError(f"Embeddings incomplets ({len(vectors)} vecteurs pour {len(texts)} fragments)")
    return vectors


_FRENCH_ERRORS = (PermanentJobError, ExtractionError, EmbeddingError, IndexingError, NotImplementedError)


def _error_text(exc: BaseException) -> str:
    """French ``status_reason`` for a failure (technical errors are labelled as such)."""
    message = str(exc).strip()
    if isinstance(exc, _FRENCH_ERRORS):
        return message or "Échec du traitement"
    if not message:
        return f"Erreur technique inattendue ({type(exc).__name__})"
    return f"Erreur technique ({type(exc).__name__}) : {message}"


async def _load_document(session: AsyncSession, job: IngestionJob) -> Document:
    if job.document_id is None:
        raise PermanentJobError("Job sans document associé")
    document = await session.get(Document, job.document_id)
    if document is None:
        raise PermanentJobError("Document introuvable (supprimé ?)")
    return document


# --- ingest -----------------------------------------------------------------------------------------


@dataclass(slots=True)
class _PreparedChunk:
    id: uuid.UUID
    ordinal: int
    text: str
    text_redacted: str
    section: str | None
    char_start: int
    char_end: int
    token_count: int
    pii: list[dict[str, Any]]


async def handle_ingest(session: AsyncSession, job: IngestionJob) -> None:
    document = await _load_document(session, job)
    if document.status == DocumentStatus.forgotten:
        async with track_step(session, job, "extract") as step:
            step.skip("Document oublié : ingestion annulée")
        return
    version_number = int((job.payload or {}).get("version") or document.current_version)
    if version_number < document.current_version:
        async with track_step(session, job, "extract") as step:
            step.skip(
                f"Version {version_number} obsolète (version courante : {document.current_version}) : ignorée"
            )
        return
    job_id, attempts, max_attempts, document_id = job.id, job.attempts, job.max_attempts, document.id
    try:
        version = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id, DocumentVersion.version == version_number
            )
        )
        if version is None:
            raise PermanentJobError(f"Version {version_number} du document introuvable")
        source = await session.get(Source, document.source_id)
        document.status = DocumentStatus.processing
        document.status_reason = None
        await session.commit()
        await _ingest(session, job, document, source, version)
    except Exception as exc:
        await _record_ingest_failure(
            session, job_id, document_id, attempts, max_attempts, list(job.steps or []), exc
        )
        raise


async def _extract(document: Document, version: DocumentVersion) -> ExtractedDocument:
    if version.object_key:
        try:
            data = await get_object_store().get(version.object_key)
        except ObjectNotFoundError as exc:
            raise PermanentJobError("Fichier original introuvable dans le stockage d'objets") from exc
        except ObjectStoreError as exc:
            raise PermanentJobError(f"Stockage d'objets inaccessible : {exc}") from exc
        filename = str((version.metadata_ or {}).get("filename") or document.title)
        try:
            return await asyncio.to_thread(extract, data, document.mime_type, filename)
        except ExtractionError as exc:
            raise PermanentJobError(str(exc)) from exc
    try:
        return extract_text_content(version.extracted_text or "", document.mime_type)
    except ExtractionError as exc:
        raise PermanentJobError(str(exc)) from exc


async def _ingest(
    session: AsyncSession,
    job: IngestionJob,
    document: Document,
    source: Source | None,
    version: DocumentVersion,
) -> None:
    # 1. extract ------------------------------------------------------------------------------------
    async with track_step(session, job, "extract", commit=True) as step:
        extracted = await _extract(document, version)
        text = extracted.text
        extraction_meta: dict[str, Any] = {"format": extracted.format, **extracted.metadata}
        if extracted.title:
            extraction_meta["title"] = extracted.title
        version.extracted_text = text
        version.metadata_ = {
            **(version.metadata_ or {}),
            "extraction": extraction_meta,
            "char_count": len(text),
        }
        if extracted.author and not document.author:
            document.author = extracted.author[:300]
        detail = f"{FORMAT_LABELS.get(extracted.format, extracted.format)} · {len(text)} caractères"
        if extracted.metadata.get("page_count"):
            detail += f" · {extracted.metadata['page_count']} page(s)"
        step.detail = detail

    # 2. pii ------------------------------------------------------------------------------------------
    async with track_step(session, job, "pii", commit=True) as step:
        pii_result = await asyncio.to_thread(analyze, text)
        step.detail = pii_summary(pii_result.entities)

    # 3. classify -------------------------------------------------------------------------------------
    async with track_step(session, job, "classify", commit=True) as step:
        declared = int(document.classification)
        manual = bool((document.metadata_ or {}).get("classification_manual"))
        source_default = int(source.default_classification) if source is not None else 1
        result = await classifier.classify(
            text,
            title=document.title,
            source_default=source_default,
            declared=declared,
            pii_entities=pii_result.entities,
            use_llm=not manual,
        )
        if manual:
            level = declared
            reasons = [f"classification fixée manuellement : {classification_code(declared)}"]
        else:
            level = max(declared, result.level)
            reasons = result.reasons
        document.metadata_ = {**(document.metadata_ or {}), "classification_reasons": reasons}
        if level > declared:
            document.classification = level
            await audit.record(
                session,
                document.project_id,
                Actor.system(),
                AuditAction.classification_change,
                "document",
                document.id,
                f"Classification de « {document.title} » relevée de {classification_code(declared)} "
                f"à {classification_code(level)}",
                {"from": declared, "to": level, "reasons": reasons, "automatic": True},
            )
            step.detail = (
                f"{classification_code(level)} ({classification_label(level)}) — relevée depuis "
                f"{classification_code(declared)} : {'; '.join(reasons[1:]) or reasons[0]}"
            )
        else:
            step.detail = f"{classification_code(level)} ({classification_label(level)}) — " + "; ".join(
                reasons
            )

    # 4. chunk ------------------------------------------------------------------------------------------
    async with track_step(session, job, "chunk", commit=True) as step:
        spans = await asyncio.to_thread(chunk_text, text)
        if not spans:
            raise PermanentJobError("Aucun fragment n'a pu être produit (texte vide après extraction)")
        prepared: list[_PreparedChunk] = []
        for span in spans:
            entities = entities_in_span(pii_result.entities, text, span.char_start, span.char_end)
            prepared.append(
                _PreparedChunk(
                    id=chunk_uuid(document.id, version.version, span.ordinal),
                    ordinal=span.ordinal,
                    text=span.text,
                    text_redacted=redact(span.text, entities),
                    section=span.section,
                    char_start=span.char_start,
                    char_end=span.char_end,
                    token_count=span.token_count,
                    pii=[e.to_dict() for e in entities],
                )
            )
        total_tokens = sum(c.token_count for c in prepared)
        noun = "fragment" if len(prepared) == 1 else "fragments"
        step.detail = f"{len(prepared)} {noun} · ~{total_tokens} tokens"

    # 5. embed ------------------------------------------------------------------------------------------
    async with track_step(session, job, "embed", commit=True) as step:
        try:
            vectors = await embed_texts(
                [embedding_input(document.title, c.section, c.text) for c in prepared]
            )
        except EmbeddingDimensionError as exc:
            raise PermanentJobError(str(exc)) from exc
        embedder = await aget_embedder()
        step.detail = f"{len(vectors)} vecteurs · {embedder.model_name} ({embedder.dim} dim.)"

    # 6. index ------------------------------------------------------------------------------------------
    async with track_step(session, job, "index") as step:
        # Pick up metadata changed while the job was running (ACL, title, tags…).
        await session.refresh(document)
        if level > document.classification and not manual:
            document.classification = level
        chunks = await _upsert_chunks(session, document, version.version, prepared)
        await opensearch.index_chunks(
            [chunk_index_doc(c, document, source, v) for c, v in zip(chunks, vectors, strict=True)],
            refresh=True,
        )
        superseded = await _supersede_previous_versions(session, document, version.version)
        now = utcnow()
        document.status = DocumentStatus.indexed
        document.status_reason = None
        document.pii_count = pii_result.count
        if source is not None:
            source.last_ingested_at = now
        detail = f"{len(chunks)} fragment(s) indexé(s) (v{version.version})"
        if superseded:
            detail += f" · {superseded} fragment(s) des versions précédentes remplacé(s)"
        step.detail = detail

    # 7. extract_memory -----------------------------------------------------------------------------------
    async with track_step(session, job, "extract_memory") as step:
        await enqueue_job(
            session,
            document.project_id,
            JobKind.extract_memory,
            document.id,
            payload={"version": version.version},
        )
        step.detail = "extraction de la mémoire planifiée (job dédié)"

    await audit.record(
        session,
        document.project_id,
        Actor.system(),
        AuditAction.document_indexed,
        "document",
        document.id,
        f"« {document.title} » indexé (v{version.version}, {len(chunks)} fragment(s), "
        f"{pii_result.count} donnée(s) personnelle(s), {classification_code(document.classification)})",
        {
            "version": version.version,
            "chunks": len(chunks),
            "pii": pii_result.counts,
            "classification": int(document.classification),
            "superseded_chunks": superseded,
        },
    )


async def _upsert_chunks(
    session: AsyncSession, document: Document, version: int, prepared: Sequence[_PreparedChunk]
) -> list[Chunk]:
    """Create/update the chunk rows of ``version`` in place (stable ids) and drop extra ordinals."""
    existing = {
        c.id: c
        for c in await session.scalars(
            select(Chunk).where(Chunk.document_id == document.id, Chunk.version == version)
        )
    }
    wanted = {c.id for c in prepared}
    stale = [c for cid, c in existing.items() if cid not in wanted]
    if stale:
        await opensearch.delete_by_ids("chunks", [str(c.id) for c in stale])
        for chunk in stale:
            await session.delete(chunk)
    rows: list[Chunk] = []
    for item in prepared:
        row = existing.get(item.id)
        if row is None:
            row = Chunk(id=item.id, project_id=document.project_id, document_id=document.id, version=version)
            session.add(row)
        row.ordinal = item.ordinal
        row.text = item.text
        row.text_redacted = item.text_redacted
        row.token_count = item.token_count
        row.section = item.section
        row.char_start = item.char_start
        row.char_end = item.char_end
        row.pii = item.pii
        row.classification = int(document.classification)
        row.acl_principals = list(document.acl_principals)
        row.status = ChunkStatus.active
        rows.append(row)
    await session.flush()
    return rows


async def _supersede_previous_versions(session: AsyncSession, document: Document, version: int) -> int:
    """Older versions' active chunks → ``superseded`` (DB + index) and ``supersedes`` relation."""
    old_ids = list(
        await session.scalars(
            select(Chunk.id).where(
                Chunk.document_id == document.id,
                Chunk.version < version,
                Chunk.status == ChunkStatus.active,
            )
        )
    )
    if old_ids:
        await session.execute(
            update(Chunk).where(Chunk.id.in_(old_ids)).values(status=ChunkStatus.superseded)
        )
        await opensearch.update_status(
            "chunks", [str(i) for i in old_ids], ChunkStatus.superseded.value, refresh=True
        )
    if version > 1:
        detail = f"Version {version} remplace la version {version - 1}"
        stmt = (
            pg_insert(Relation)
            .values(
                id=uuid.uuid4(),
                project_id=document.project_id,
                src_type=RelationNodeType.document.value,
                src_id=document.id,
                rel_type=RelationType.supersedes.value,
                dst_type=RelationNodeType.document.value,
                dst_id=document.id,
                confidence=1.0,
                detail=detail,
            )
            .on_conflict_do_update(index_elements=["src_id", "rel_type", "dst_id"], set_={"detail": detail})
        )
        await session.execute(stmt)
    return len(old_ids)


async def _record_ingest_failure(
    session: AsyncSession,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    attempts: int,
    max_attempts: int,
    steps: list[dict[str, Any]],
    exc: BaseException,
) -> None:
    """Persist the failed steps and the document status before the worker rolls back."""
    message = _error_text(exc)
    permanent = isinstance(exc, PermanentJobError | NotImplementedError) or attempts >= max_attempts
    try:
        await session.rollback()
        job = await session.get(IngestionJob, job_id, populate_existing=True)
        document = await session.get(Document, document_id, populate_existing=True)
        if job is not None:
            job.steps = steps
        if document is not None and document.status != DocumentStatus.forgotten:
            if permanent:
                document.status = DocumentStatus.failed
                document.status_reason = message[:1000]
                await audit.record(
                    session,
                    document.project_id,
                    Actor.system(),
                    AuditAction.document_failed,
                    "document",
                    document.id,
                    f"Échec de l'ingestion de « {document.title} » : {message[:300]}",
                    {"attempts": attempts, "error": message[:1000]},
                )
            else:
                document.status = DocumentStatus.pending
                document.status_reason = (
                    f"Échec temporaire (tentative {attempts}/{max_attempts}) : {message[:500]} — "
                    "nouvelle tentative programmée"
                )
        await session.commit()
    except Exception:  # never mask the original error
        logger.exception("Unable to record the failure of ingestion job %s", job_id)
        await session.rollback()


# --- reindex ----------------------------------------------------------------------------------------


async def handle_reindex(session: AsyncSession, job: IngestionJob) -> None:
    payload = job.payload or {}
    mode = str(payload.get("mode") or "metadata")
    if mode not in {"metadata", "full"}:
        raise PermanentJobError(f"Mode de réindexation inconnu : {mode}")
    if job.document_id is not None:
        document = await _load_document(session, job)
        documents = [document]
    else:
        documents = list(
            await session.scalars(
                select(Document).where(
                    Document.project_id == job.project_id,
                    Document.status.in_([DocumentStatus.indexed, DocumentStatus.failed]),
                )
            )
        )
    documents = [d for d in documents if d.status != DocumentStatus.forgotten]
    if not documents:
        async with track_step(session, job, "index") as step:
            step.skip("Aucun document à réindexer")
        return

    total = 0
    if mode == "metadata":
        async with track_step(session, job, "index") as step:
            for document in documents:
                source = await session.get(Source, document.source_id)
                chunk_rows = list(
                    await session.scalars(
                        select(Chunk).where(
                            Chunk.document_id == document.id, Chunk.status != ChunkStatus.forgotten
                        )
                    )
                )
                fields = document_index_fields(document, source)
                for chunk in chunk_rows:
                    chunk.classification = int(document.classification)
                    chunk.acl_principals = list(document.acl_principals)
                await opensearch.update_fields("chunks", [str(c.id) for c in chunk_rows], fields)
                total += len(chunk_rows)
            await opensearch.refresh("chunks")
            step.detail = f"métadonnées de {total} fragment(s) synchronisées ({len(documents)} document(s))"
        return

    async with track_step(session, job, "embed", commit=True) as step:
        batches: list[tuple[Document, Source | None, list[Chunk], list[list[float]]]] = []
        for document in documents:
            source = await session.get(Source, document.source_id)
            chunk_rows = list(
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.document_id == document.id, Chunk.status != ChunkStatus.forgotten)
                    .order_by(Chunk.version, Chunk.ordinal)
                )
            )
            if not chunk_rows:
                continue
            try:
                vectors = await embed_texts(
                    [embedding_input(document.title, c.section, c.text) for c in chunk_rows]
                )
            except EmbeddingDimensionError as exc:
                raise PermanentJobError(str(exc)) from exc
            batches.append((document, source, chunk_rows, vectors))
            total += len(chunk_rows)
        step.detail = f"{total} fragment(s) ré-encodés ({len(batches)} document(s))"
    async with track_step(session, job, "index") as step:
        for document, source, chunk_rows, vectors in batches:
            for chunk in chunk_rows:
                chunk.classification = int(document.classification)
                chunk.acl_principals = list(document.acl_principals)
            await opensearch.index_chunks(
                [chunk_index_doc(c, document, source, v) for c, v in zip(chunk_rows, vectors, strict=True)]
            )
        await opensearch.refresh("chunks")
        step.detail = f"{total} fragment(s) réindexés"


# --- forget -----------------------------------------------------------------------------------------


async def _call_propagate_document_forget(session: AsyncSession, document: Document, actor: Actor) -> int:
    """Call the memory teammate's ``propagate_document_forget`` whatever its exact signature."""
    from app.memory import lifecycle

    function = lifecycle.propagate_document_forget
    parameters = inspect.signature(function).parameters
    if "document" in parameters:
        result = await function(session, document, actor)  # type: ignore[call-arg]
    elif "document_id" in parameters:
        result = await function(session, document.project_id, document.id, actor=actor)  # type: ignore[call-arg]
    else:
        result = await function(session, document, actor)  # type: ignore[call-arg]
    return int(result or 0)


async def handle_forget(session: AsyncSession, job: IngestionJob) -> None:
    document = await _load_document(session, job)
    payload = job.payload or {}
    actor = actor_from_payload(payload)
    now = utcnow()
    if document.status != DocumentStatus.forgotten:
        document.status = DocumentStatus.forgotten
        document.forgotten_at = document.forgotten_at or now
        if actor.type == ActorType.user and document.forgotten_by is None:
            document.forgotten_by = actor.id

    async with track_step(session, job, "index", commit=True) as step:
        deleted = await opensearch.delete_by_query(
            "chunks", {"term": {"document_id": str(document.id)}}, refresh=True
        )
        step.detail = f"{deleted} fragment(s) supprimé(s) de l'index"

    async with track_step(session, job, "purge", commit=True) as step:
        result = await session.execute(
            update(Chunk)
            .where(Chunk.document_id == document.id)
            .values(status=ChunkStatus.forgotten, text=FORGOTTEN_TEXT, text_redacted=FORGOTTEN_TEXT, pii=[])
            .returning(Chunk.id)
        )
        chunk_count = len(result.all())
        versions = list(
            await session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id))
        )
        purged_files = 0
        store = get_object_store()
        for version in versions:
            if version.object_key:
                try:
                    if await store.delete(version.object_key):
                        purged_files += 1
                except ObjectStoreError as exc:
                    logger.warning("Unable to delete object %s: %s", version.object_key, exc)
                    raise
                version.object_key = None
            version.extracted_text = FORGOTTEN_TEXT
        document.pii_count = 0
        document.status_reason = None
        step.detail = (
            f"{chunk_count} fragment(s) remplacé(s) par « {FORGOTTEN_TEXT} », "
            f"{len(versions)} version(s) purgée(s), {purged_files} fichier(s) supprimé(s)"
        )

    memory_propagated = False
    async with track_step(session, job, "memory", commit=True) as step:
        try:
            affected = await _call_propagate_document_forget(session, document, actor)
            memory_propagated = True
            step.detail = f"{affected} item(s) mémoire dérivé(s) oublié(s) ou dévalué(s)"
        except NotImplementedError:
            logger.warning("Memory propagation of forgotten document %s unavailable", document.id)
            step.skip("propagation mémoire indisponible sur cette instance")

    tombstone_id = payload.get("tombstone_id")
    tombstone: Tombstone | None = None
    if tombstone_id:
        tombstone = await session.get(Tombstone, uuid.UUID(str(tombstone_id)))
    if tombstone is None:
        tombstone = await session.scalar(
            select(Tombstone)
            .where(Tombstone.target_type == TombstoneTarget.document, Tombstone.target_id == document.id)
            .order_by(Tombstone.created_at.desc())
            .limit(1)
        )
    if tombstone is not None and memory_propagated:
        tombstone.propagated_at = utcnow()


# --- memory delegation ------------------------------------------------------------------------------


async def handle_extract_memory(session: AsyncSession, job: IngestionJob) -> None:
    try:
        from app.memory.extractor import extract_from_document
    except ImportError as exc:
        raise NotImplementedError("Extraction mémoire non disponible sur cette instance") from exc
    await extract_from_document(session, job)


async def handle_consolidate(session: AsyncSession, job: IngestionJob) -> None:
    try:
        from app.memory.consolidation import run_consolidation
    except ImportError as exc:
        raise NotImplementedError("Consolidation mémoire non disponible sur cette instance") from exc
    await run_consolidation(session, job)


__all__ = [
    "CHUNK_ID_NAMESPACE",
    "FORGOTTEN_TEXT",
    "actor_from_payload",
    "actor_payload",
    "chunk_index_doc",
    "chunk_uuid",
    "document_index_fields",
    "embed_texts",
    "handle_consolidate",
    "handle_extract_memory",
    "handle_forget",
    "handle_ingest",
    "handle_reindex",
    "run_job",
]
