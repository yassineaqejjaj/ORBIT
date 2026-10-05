"""Connector services (docs/FEATURES.md F5): configuration, secrets, source, sync requests, scheduling.

Synced documents are written by a *connector principal*: a system actor (``Connecteur « nom »`` in the
audit log) that sees every document of the project so updates of restricted documents are possible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors import REGISTRY, secrets
from app.connectors.base import BaseConnector
from app.db import utcnow
from app.deps import ProjectAccess
from app.enums import ActorType, DocumentStatus, JobKind, JobStatus, Role
from app.errors import ApiError, validation_error
from app.features.feed import security
from app.governance.acl import PROJECT_ALL
from app.ingestion.pipeline import actor_payload
from app.ingestion.queue import enqueue_job
from app.models import Document, IngestionJob, Project, Source
from app.models.connector import Connector, ConnectorRun
from app.services import audit
from app.services.audit import Actor, AuditAction

ACTIVE_RUN_STATUSES = ("queued", "running")
EDITORS_ACL = ["role:editor"]
#: Display-only scope names (labels of the chosen sites/spaces), kept next to the scope ids.
DISPLAY_KEYS = ("scope_labels",)


class Action:
    """Audit action names (``connector.<verb>``, consistent with F2's ``webhook.<verb>``)."""

    create = "connector.create"
    update = "connector.update"
    delete = "connector.delete"
    test = "connector.test"
    sync_requested = "connector.sync_requested"
    synced = "connector.synced"
    failed = "connector.failed"


def connector_class(type_: str) -> type[BaseConnector]:
    try:
        return REGISTRY[type_]
    except KeyError as exc:
        raise validation_error(f"Type de connecteur inconnu : {type_}") from exc


def validate_config(type_: str, config: dict[str, Any], *, require_scope: bool) -> dict[str, Any]:
    cls = connector_class(type_)
    try:
        clean = cls.validate_config(dict(config or {}), require_scope=require_scope)
    except ValueError as exc:
        raise validation_error(str(exc)) from exc
    labels = (config or {}).get("scope_labels")
    if isinstance(labels, list):
        clean["scope_labels"] = [str(label)[:200] for label in labels[:100]]
    return clean


async def check_base_url(type_: str, config: dict[str, Any]) -> None:
    """Anti-SSRF check of the user-provided endpoints (HTTPS and public address outside development)."""
    for url in connector_class(type_).base_urls(config):
        try:
            await security.check_destination(url)
        except security.UnsafeUrlError as exc:
            raise validation_error(str(exc).replace("du webhook", "du service")) from exc


def normalize_secret(type_: str, config: dict[str, Any], secret: str) -> str:
    """Secret as stored (MCP: JSON object of the preset's secret fields); 422 when a field is missing."""
    try:
        return connector_class(type_).normalize_secret(config, secret)
    except ValueError as exc:
        raise validation_error(str(exc)) from exc


def secret_hint(type_: str, config: dict[str, Any], secret: str) -> str:
    return connector_class(type_).secret_hint_of(config, secret)


def check_mcp_allowed(type_: str, config: dict[str, Any], principal: Any) -> None:
    """Custom MCP servers (arbitrary command/URL): ``ORBIT_MCP_ALLOW_CUSTOM`` and platform admins only."""
    if type_ != "mcp":
        return
    from app.connectors.mcp import get_preset

    try:
        preset = get_preset(config.get("preset"))
    except ValueError as exc:
        raise validation_error(str(exc)) from exc
    if not preset.admin_only:
        return
    if not settings.mcp_allow_custom:
        raise ApiError(
            403,
            "Les serveurs MCP personnalisés sont désactivés (ORBIT_MCP_ALLOW_CUSTOM=false)",
            code="mcp_custom_disabled",
        )
    if not getattr(principal, "is_admin", False) or not getattr(principal, "is_user", True):
        raise ApiError(
            403,
            "Seuls les administrateurs de la plateforme peuvent configurer un serveur MCP personnalisé",
            code="mcp_custom_forbidden",
        )


def acl_for(connector: Connector) -> list[str]:
    return list(EDITORS_ACL) if connector.restrict_to_editors else [PROJECT_ALL]


def instantiate(type_: str, config: dict[str, Any], secret: str) -> BaseConnector:
    return connector_class(type_)(config, secret)


def build(connector: Connector) -> BaseConnector:
    """Connector client with the decrypted secret (503 when the key is missing or changed)."""
    if not connector.secret_ciphertext:
        raise validation_error("Secret du connecteur absent : ressaisissez-le")
    return instantiate(
        connector.type, dict(connector.config or {}), secrets.decrypt(connector.secret_ciphertext)
    )


def type_label(type_: str, config: dict[str, Any] | None = None) -> str:
    cls = REGISTRY.get(type_)
    if cls is None:
        return type_
    return cls.display_label(dict(config or {})) if config is not None else cls.label


def actor_for(connector: Connector) -> Actor:
    return Actor(ActorType.system, None, f"Connecteur « {connector.name} »")


# --- Connector principal -----------------------------------------------------------------------------


@dataclass(slots=True)
class ConnectorPrincipal:
    """Duck-typed :class:`app.deps.Principal` used by the sync to call ``ingest_content``."""

    label: str
    kind: str = "user"
    user: None = None
    agent: None = None
    is_admin: bool = True
    clearance: int = 3
    is_user: bool = True
    is_agent: bool = False
    user_id: None = None
    agent_id: None = None

    @property
    def actor(self) -> Actor:
        return Actor(ActorType.system, None, self.label)


def connector_access(project: Project, connector: Connector) -> ProjectAccess:
    principal: Any = ConnectorPrincipal(label=actor_for(connector).label)
    return ProjectAccess(project=project, principal=principal, role=Role.owner)


# --- Source ------------------------------------------------------------------------------------------


async def ensure_source(session: AsyncSession, connector: Connector, actor: Actor) -> Source:
    """The connector's own source (created on first use); defaults follow the connector settings."""
    cls = connector_class(connector.type)
    config = dict(connector.config or {})
    label = cls.display_label(config)
    kind = cls.kind_for(config)
    source = await session.get(Source, connector.source_id) if connector.source_id else None
    if source is not None and source.project_id == connector.project_id:
        source.default_classification = int(connector.default_classification)
        source.default_acl = acl_for(connector)
        return source
    source = Source(
        project_id=connector.project_id,
        name=f"{label} — {connector.name}"[:200],
        kind=kind,
        description=f"Source alimentée par le connecteur {label} « {connector.name} »",
        default_classification=int(connector.default_classification),
        default_acl=acl_for(connector),
        config={"connector_id": str(connector.id), "connector_type": connector.type},
    )
    session.add(source)
    await session.flush()
    connector.source_id = source.id
    await audit.record(
        session,
        connector.project_id,
        actor,
        AuditAction.source_create,
        "source",
        source.id,
        summary=f"Création de la source « {source.name} » (connecteur)",
        details={"kind": kind.value, "connector_id": str(connector.id)},
    )
    return source


async def document_counts(session: AsyncSession, source_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not source_ids:
        return {}
    rows = await session.execute(
        select(Document.source_id, func.count())
        .where(Document.source_id.in_(source_ids), Document.status != DocumentStatus.forgotten)
        .group_by(Document.source_id)
    )
    return {row[0]: int(row[1]) for row in rows}


# --- Runs --------------------------------------------------------------------------------------------


async def active_run(session: AsyncSession, connector_id: uuid.UUID) -> ConnectorRun | None:
    return await session.scalar(
        select(ConnectorRun)
        .where(ConnectorRun.connector_id == connector_id, ConnectorRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(ConnectorRun.created_at.desc())
        .limit(1)
    )


async def last_runs(session: AsyncSession, connector_ids: list[uuid.UUID]) -> dict[uuid.UUID, ConnectorRun]:
    if not connector_ids:
        return {}
    rows = await session.scalars(
        select(ConnectorRun)
        .where(ConnectorRun.connector_id.in_(connector_ids))
        .distinct(ConnectorRun.connector_id)
        .order_by(ConnectorRun.connector_id, ConnectorRun.created_at.desc())
    )
    return {run.connector_id: run for run in rows}


async def request_sync(
    session: AsyncSession, connector: Connector, trigger: str, actor: Actor
) -> ConnectorRun:
    """Queue a ``connector_sync`` job and its run row (the caller commits)."""
    run = ConnectorRun(
        connector_id=connector.id,
        project_id=connector.project_id,
        trigger=trigger,
        status="queued",
        progress={"phase": "queued", "message": "Synchronisation en attente du worker…"},
    )
    session.add(run)
    await session.flush()
    job = await enqueue_job(
        session,
        connector.project_id,
        JobKind.connector_sync,
        payload={"connector_id": str(connector.id), "run_id": str(run.id), "actor": actor_payload(actor)},
        max_attempts=2,
    )
    run.job_id = job.id
    if connector.status != "paused":
        connector.status = "syncing"
    return run


async def schedule_due_syncs(session: AsyncSession) -> int:
    """Maintenance hook: queue the scheduled syncs that are due (no run already queued/running)."""
    now = utcnow()
    busy = select(ConnectorRun.id).where(
        ConnectorRun.connector_id == Connector.id, ConnectorRun.status.in_(ACTIVE_RUN_STATUSES)
    )
    due = await session.scalars(
        select(Connector)
        .where(
            Connector.status != "paused",
            Connector.schedule_minutes > 0,
            Connector.secret_ciphertext.is_not(None),
            or_(
                Connector.last_sync_at.is_(None),
                Connector.last_sync_at <= now - func.make_interval(0, 0, 0, 0, 0, Connector.schedule_minutes),
            ),
            ~busy.exists(),
        )
        .order_by(Connector.last_sync_at.asc().nulls_first())
        .limit(100)
    )
    count = 0
    for connector in due:
        await request_sync(session, connector, "schedule", Actor.system())
        count += 1
    return count


async def fail_orphan_runs(session: AsyncSession, older_than: timedelta = timedelta(hours=6)) -> int:
    """Runs stuck in ``queued``/``running`` whose job is gone or finished (worker crash) are closed."""
    cutoff = utcnow() - older_than
    stuck = await session.scalars(
        select(ConnectorRun).where(
            ConnectorRun.status.in_(ACTIVE_RUN_STATUSES),
            ConnectorRun.created_at < cutoff,
            ~select(IngestionJob.id)
            .where(
                and_(
                    IngestionJob.id == ConnectorRun.job_id,
                    IngestionJob.status.in_((JobStatus.queued, JobStatus.running)),
                )
            )
            .exists(),
        )
    )
    count = 0
    for run in stuck:
        run.status = "failed"
        run.error = "Synchronisation interrompue (worker arrêté)"
        run.finished_at = utcnow()
        connector = await session.get(Connector, run.connector_id)
        if connector is not None and connector.status == "syncing":
            connector.status = "error"
            connector.last_error = run.error
        count += 1
    return count


async def run_connector_maintenance(session: AsyncSession) -> dict[str, int]:
    summary = {
        "connector_runs_closed": await fail_orphan_runs(session),
        "connector_syncs_scheduled": await schedule_due_syncs(session),
    }
    return {k: v for k, v in summary.items() if v}


def default_schedule() -> int:
    return int(settings.connector_default_schedule_minutes)


def suggested_task(connector: Connector) -> str:
    """Task proposed by the wizard's last step (« Votre premier contexte »)."""
    labels = [str(label) for label in (connector.config or {}).get("scope_labels") or []]
    if connector.type == "mcp":
        from app.connectors.mcp import PRESETS

        preset = PRESETS.get(str((connector.config or {}).get("preset") or ""))
        return preset.suggested_task if preset else "Résumer les décisions, risques et points ouverts récents"
    if connector.type == "jira":
        return (
            "Faire le point sur les tickets récents : décisions prises, blocages, "
            "risques et prochaines étapes"
        )
    if connector.type == "confluence":
        scope = ", ".join(labels or list((connector.config or {}).get("space_keys") or [])[:3])
        where = f" de l'espace {scope}" if scope else ""
        return f"Résumer les décisions, contraintes et points ouverts documentés{where}"
    where = f" de {', '.join(labels[:3])}" if labels else ""
    return f"Préparer une synthèse des documents récents{where} : décisions, risques et points ouverts"
