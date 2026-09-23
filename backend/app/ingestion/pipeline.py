"""Job dispatcher (interface — implemented by the ingestion teammate).

``run_job`` is called by the worker (``app.worker``) inside its own session with a job already
claimed (``running``). The handler must:

* perform the work for ``job.kind`` (ARCHITECTURE §7):
  - ``ingest``: extract → pii → classify → chunk → embed → index → extract_memory (enqueue an
    ``extract_memory`` job), each step timed via ``app.ingestion.queue.track_step`` so ``job.steps``
    is filled for the Sources screen; update ``Document.status`` (``processing`` → ``indexed`` /
    ``failed``), ``status_reason``, ``pii_count``, ``current_version`` and the source's
    ``last_ingested_at``; new version ⇒ previous chunks ``superseded`` + relation ``supersedes``;
  - ``reindex``: re-embed / re-index the current version (metadata changes, model change);
  - ``forget``: propagate a tombstone (index deletion, derived memory, Valkey, snapshots);
  - ``consolidate``: memory consolidation / confidence decay (``app.memory.lifecycle``);
  - ``extract_memory``: derive memory items from the document's chunks.
* raise ``app.ingestion.queue.PermanentJobError`` for non-retryable failures; any other exception
  triggers a retry with backoff;
* NOT call ``mark_succeeded`` / ``mark_failed`` nor commit the final state: the worker does it
  (intermediate commits for progress are allowed).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import JobKind
from app.models import IngestionJob


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


async def handle_ingest(session: AsyncSession, job: IngestionJob) -> None:
    raise NotImplementedError("Pipeline d'ingestion non implémenté")


async def handle_reindex(session: AsyncSession, job: IngestionJob) -> None:
    raise NotImplementedError("Réindexation non implémentée")


async def handle_forget(session: AsyncSession, job: IngestionJob) -> None:
    raise NotImplementedError("Propagation de l'oubli non implémentée")


async def handle_consolidate(session: AsyncSession, job: IngestionJob) -> None:
    raise NotImplementedError("Consolidation mémoire non implémentée")


async def handle_extract_memory(session: AsyncSession, job: IngestionJob) -> None:
    raise NotImplementedError("Extraction mémoire non implémentée")
