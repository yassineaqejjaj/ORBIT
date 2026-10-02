"""Connector synchronisation — job ``kind=connector_sync`` (docs/FEATURES.md F5).

One run: connect, stream the changes since the stored cursor, map upserts onto
``ingestion.service.ingest_content`` (dedup by content hash, new version when changed) and deletions onto
the selective-forget path, confirm deletions for connectors without delta feeds, then persist the new
cursor and the run statistics. Progress is committed every few items so the wizard can poll it live.
A ``connector.synced`` audit entry (→ change event, F2) is recorded when something changed, on failure
and for manual/initial runs.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import service
from app.connectors.base import BaseConnector, Change, ConnectorError
from app.db import utcnow
from app.enums import DocumentStatus
from app.errors import ApiError
from app.ingestion.service import ContentIn, forget_document, ingest_content
from app.models import Document, IngestionJob, Project, Source
from app.models.connector import Connector, ConnectorRun
from app.services import audit
from app.services.audit import Actor

logger = logging.getLogger(__name__)

COMMIT_EVERY = 10
MAX_ERROR_SAMPLES = 20


async def handle_connector_sync(session: AsyncSession, job: IngestionJob) -> None:
    payload = job.payload or {}
    try:
        connector_id = uuid.UUID(str(payload.get("connector_id")))
    except ValueError:
        return
    connector = await session.get(Connector, connector_id)
    if connector is None:  # deleted meanwhile
        return
    run: ConnectorRun | None = None
    if payload.get("run_id"):
        try:
            run = await session.get(ConnectorRun, uuid.UUID(str(payload["run_id"])))
        except ValueError:
            run = None
    if run is None:
        run = ConnectorRun(connector_id=connector.id, project_id=connector.project_id, trigger="schedule")
        session.add(run)
    run.job_id = job.id
    await run_sync(session, connector, run)


def _progress(run: ConnectorRun, phase: str, message: str) -> None:
    run.progress = {
        "phase": phase,
        "message": message,
        "fetched": run.fetched,
        "created": run.created,
        "updated": run.updated,
        "forgotten": run.forgotten,
        "errors": run.errors,
    }


def _sample(run: ConnectorRun, item: str, error: str) -> None:
    run.errors += 1
    if len(run.error_samples or []) < MAX_ERROR_SAMPLES:
        run.error_samples = [*(run.error_samples or []), {"item": item[:300], "error": error[:500]}]


async def run_sync(session: AsyncSession, connector: Connector, run: ConnectorRun) -> ConnectorRun:
    started = time.perf_counter()
    actor = service.actor_for(connector)
    run.status = "running"
    run.started_at = utcnow()
    run.fetched = run.created = run.updated = run.unchanged = run.skipped = run.forgotten = run.errors = 0
    run.error_samples = []
    run.error = None
    if connector.status != "paused":
        connector.status = "syncing"
    _progress(run, "connecting", "Connexion au service…")
    await session.commit()

    impl: BaseConnector | None = None
    try:
        impl = service.build(connector)
        await service.check_base_url(connector.type, dict(connector.config or {}))
        project = await session.get(Project, connector.project_id)
        if project is None:
            raise ConnectorError("Projet introuvable")
        source = await service.ensure_source(session, connector, actor)
        access = service.connector_access(project, connector)
        _progress(run, "fetching", "Récupération des contenus…")
        await session.commit()
        async for change in impl.changes(dict(connector.cursor or {})):
            run.fetched += 1
            await _apply(session, connector, run, source, access, change, actor)
            if run.fetched % COMMIT_EVERY == 0:
                _progress(run, "fetching", f"{run.fetched} élément(s) traité(s)…")
                await session.commit()
        _progress(run, "deletions", "Vérification des suppressions à la source…")
        await session.commit()
        known = set(
            await session.scalars(
                select(Document.external_id).where(
                    Document.source_id == source.id,
                    Document.status != DocumentStatus.forgotten,
                    Document.external_id.is_not(None),
                )
            )
        )
        for external_id in await impl.confirm_deleted({str(k) for k in known if k}):
            run.forgotten += await _forget(session, connector, source, external_id, actor)
        connector.cursor = {**(connector.cursor or {}), **impl.next_cursor}
        run.status = "partial" if run.errors else "succeeded"
        connector.last_error = None if not run.errors else f"{run.errors} élément(s) en erreur"
        if connector.status != "paused":
            connector.status = "ok"
        _progress(run, "done", "Synchronisation terminée")
    except (ConnectorError, ApiError) as exc:
        message = exc.message if isinstance(exc, ConnectorError) else str(exc.detail)
        await _fail(session, connector, run, message)
    except Exception as exc:  # never leave the run « running »
        logger.exception("Connector %s sync failed", connector.id)
        await _fail(session, connector, run, f"Erreur inattendue : {type(exc).__name__}")
    finally:
        if impl is not None:
            await impl.aclose()

    run.finished_at = utcnow()
    run.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    connector.last_sync_at = run.finished_at
    changed = run.created + run.updated + run.forgotten
    if changed or run.status == "failed" or run.errors or run.trigger != "schedule":
        await _audit_run(session, connector, run, actor)
    await session.commit()
    return run


async def _fail(session: AsyncSession, connector: Connector, run: ConnectorRun, message: str) -> None:
    await session.rollback()
    await session.refresh(connector)
    await session.refresh(run)
    run.status = "failed"
    run.error = message[:1000]
    connector.last_error = message[:1000]
    if connector.status != "paused":
        connector.status = "error"
    _progress(run, "failed", message[:300])


async def _audit_run(session: AsyncSession, connector: Connector, run: ConnectorRun, actor: Actor) -> None:
    label = service.type_label(connector.type)
    if run.status == "failed":
        summary = f"Échec de la synchronisation {label} « {connector.name} » : {run.error}"
    else:
        summary = (
            f"Connecteur {label} « {connector.name} » synchronisé : {run.created} créé(s), "
            f"{run.updated} mis à jour, {run.forgotten} oublié(s)"
            + (f", {run.errors} erreur(s)" if run.errors else "")
        )
    await audit.record(
        session,
        connector.project_id,
        actor,
        service.Action.synced,
        "connector",
        connector.id,
        summary=summary,
        details={
            "run_id": str(run.id),
            "status": run.status,
            "trigger": run.trigger,
            "documents": run.fetched,
            "created": run.created,
            "updated": run.updated,
            "forgotten": run.forgotten,
            "failed": run.errors,
            "duration_ms": run.duration_ms,
        },
    )


async def _apply(
    session: AsyncSession,
    connector: Connector,
    run: ConnectorRun,
    source: Source,
    access: Any,
    change: Change,
    actor: Actor,
) -> None:
    if change.deleted:
        run.forgotten += await _forget(session, connector, source, change.external_id, actor)
        return
    label = change.title or change.external_id
    if change.error:
        _sample(run, label, change.error)
        return
    if change.skip_reason:
        run.skipped += 1
        return
    content = ContentIn(
        title=(change.title or change.external_id)[:500],
        mime_type=change.mime_type,
        data=change.data,
        text=change.text if change.data is None else None,
        filename=change.filename,
        external_id=change.external_id,
        uri=change.uri,
        author=change.author,
        classification=int(connector.default_classification),
        acl_principals=service.acl_for(connector),
        source_updated_at=change.updated_at,
        metadata={k: v for k, v in change.metadata.items() if v is not None},
    )
    try:
        async with session.begin_nested():
            outcome = await ingest_content(session, access, source, content)
    except ApiError as exc:
        if exc.status_code == 409:  # forgotten in ORBIT: never re-ingested under the same id
            run.skipped += 1
        else:
            _sample(run, label, str(exc.detail))
        return
    except Exception as exc:
        logger.warning("Connector %s: item %s failed: %s", connector.id, change.external_id, exc)
        _sample(run, label, f"{type(exc).__name__}: {exc}")
        return
    if outcome.created:
        run.created += 1
    elif outcome.new_version:
        run.updated += 1
    else:
        run.unchanged += 1


async def _forget(
    session: AsyncSession, connector: Connector, source: Source, external_id: str, actor: Actor
) -> int:
    document = await session.scalar(
        select(Document).where(
            Document.source_id == source.id,
            Document.external_id == external_id,
            Document.status != DocumentStatus.forgotten,
        )
    )
    if document is None:
        return 0
    await forget_document(session, document, actor, f"Supprimé à la source (connecteur « {connector.name} »)")
    return 1
