"""Router `connectors` — SharePoint/OneDrive, Confluence and Jira connectors (docs/FEATURES.md F5).

Roles: members read the list, details and runs; editors trigger manual syncs; owners create, test,
edit and delete connectors. Secrets are Fernet-encrypted (``ORBIT_ENCRYPTION_KEY``, 503
``encryption_key_missing`` without it) and never returned (masked hint only). User-provided base URLs
go through the F2 anti-SSRF check (HTTPS and public addresses outside development).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import REGISTRY, secrets, service
from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.schemas import (
    ConnectorIn,
    ConnectorOut,
    ConnectorPatch,
    ConnectorRetestIn,
    ConnectorRunOut,
    ConnectorTestIn,
    ConnectorTestOut,
    ConnectorTypeOut,
    ScopeOptionOut,
)
from app.deps import EditorAccess, OwnerAccess, ProjectAccess, SessionDep, ViewerAccess
from app.errors import conflict, not_found, validation_error
from app.models.connector import Connector, ConnectorRun
from app.schemas import Page, PageParams, page_params
from app.schemas.common import make_page
from app.services import audit

router = APIRouter(prefix="/projects/{slug}/connectors", tags=["connectors"])

NOT_FOUND = "Connecteur introuvable"
MAX_CONNECTORS = 20
TEST_MAX_RETRIES = 1


async def _load(session: AsyncSession, access: ProjectAccess, connector_id: uuid.UUID) -> Connector:
    connector = await session.get(Connector, connector_id)
    if connector is None or connector.project_id != access.project_id:
        raise not_found(NOT_FOUND)
    return connector


async def _serialize(session: AsyncSession, connectors: Sequence[Connector]) -> list[ConnectorOut]:
    runs = await service.last_runs(session, [c.id for c in connectors])
    counts = await service.document_counts(session, [c.source_id for c in connectors if c.source_id])
    out: list[ConnectorOut] = []
    for connector in connectors:
        run = runs.get(connector.id)
        out.append(
            ConnectorOut(
                id=connector.id,
                type=connector.type,  # type: ignore[arg-type]
                type_label=service.type_label(connector.type),
                name=connector.name,
                config=dict(connector.config or {}),
                has_secret=bool(connector.secret_ciphertext),
                secret_hint=connector.secret_hint,
                schedule_minutes=connector.schedule_minutes,
                status=connector.status,
                paused=connector.status == "paused",
                default_classification=connector.default_classification,
                restrict_to_editors=connector.restrict_to_editors,
                acl_principals=service.acl_for(connector),
                last_sync_at=connector.last_sync_at,
                last_error=connector.last_error,
                source_id=connector.source_id,
                document_count=counts.get(connector.source_id, 0) if connector.source_id else 0,
                last_run=ConnectorRunOut.model_validate(run) if run else None,
                suggested_task=service.suggested_task(connector),
                created_at=connector.created_at,
                updated_at=connector.updated_at,
            )
        )
    return out


async def _one(session: AsyncSession, connector: Connector) -> ConnectorOut:
    return (await _serialize(session, [connector]))[0]


async def _run_test(impl: BaseConnector) -> ConnectorTestOut:
    started = time.perf_counter()
    impl.http.max_retries = TEST_MAX_RETRIES
    try:
        result = await impl.test()
        out = ConnectorTestOut(
            ok=result.ok,
            message=result.message,
            account=result.account,
            scope_options=[ScopeOptionOut.model_validate(option) for option in result.scope_options],
            duration_ms=0,
        )
    except ConnectorError as exc:
        out = ConnectorTestOut(ok=False, message=exc.message, duration_ms=0)
    finally:
        await impl.aclose()
    out.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    return out


@router.get("/types", response_model=list[ConnectorTypeOut], summary="Types de connecteurs disponibles")
async def list_types(access: ViewerAccess) -> list[ConnectorTypeOut]:
    return [
        ConnectorTypeOut(type=cls.type, label=cls.label, source_kind=cls.source_kind.value)  # type: ignore[arg-type]
        for cls in REGISTRY.values()
    ]


@router.get("", response_model=list[ConnectorOut], summary="Connecteurs du projet")
async def list_connectors(access: ViewerAccess, session: SessionDep) -> list[ConnectorOut]:
    rows = await session.scalars(
        select(Connector).where(Connector.project_id == access.project_id).order_by(Connector.created_at)
    )
    return await _serialize(session, list(rows))


@router.post("/test", response_model=ConnectorTestOut, summary="Tester des identifiants (sans ingestion)")
async def test_credentials(
    body: ConnectorTestIn, access: OwnerAccess, session: SessionDep
) -> ConnectorTestOut:
    config = service.validate_config(body.type, body.config, require_scope=False)
    await service.check_base_url(body.type, config)
    result = await _run_test(service.instantiate(body.type, config, body.secret))
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        service.Action.test,
        "connector",
        None,
        summary=(
            f"Test des identifiants {service.type_label(body.type)} : {'réussi' if result.ok else 'échec'}"
        ),
        details={"type": body.type, "ok": result.ok},
    )
    await session.commit()
    return result


@router.post(
    "", response_model=ConnectorOut, status_code=status.HTTP_201_CREATED, summary="Créer un connecteur"
)
async def create_connector(body: ConnectorIn, access: OwnerAccess, session: SessionDep) -> ConnectorOut:
    secrets.require_encryption()  # 503 encryption_key_missing
    config = service.validate_config(body.type, body.config, require_scope=True)
    await service.check_base_url(body.type, config)
    count = await session.scalar(
        select(func.count()).select_from(Connector).where(Connector.project_id == access.project_id)
    )
    if int(count or 0) >= MAX_CONNECTORS:
        raise validation_error(f"Nombre maximal de connecteurs atteint ({MAX_CONNECTORS})")
    connector = Connector(
        project_id=access.project_id,
        type=body.type,
        name=body.name,
        config=config,
        secret_ciphertext=secrets.encrypt(body.secret),
        secret_hint=secrets.hint(body.secret),
        schedule_minutes=service.default_schedule()
        if body.schedule_minutes is None
        else body.schedule_minutes,
        status="idle",
        default_classification=body.default_classification,
        restrict_to_editors=body.restrict_to_editors,
        cursor={},
        created_by_id=access.principal.user_id,
    )
    session.add(connector)
    await session.flush()
    actor = access.principal.actor
    await service.ensure_source(session, connector, actor)
    await audit.record(
        session,
        access.project_id,
        actor,
        service.Action.create,
        "connector",
        connector.id,
        summary=f"Connecteur {service.type_label(body.type)} « {body.name} » créé",
        details={
            "type": body.type,
            "default_classification": body.default_classification,
            "restrict_to_editors": body.restrict_to_editors,
            "schedule_minutes": connector.schedule_minutes,
        },
    )
    if body.start_sync:
        await service.request_sync(session, connector, "initial", actor)
    await session.commit()
    await session.refresh(connector)
    return await _one(session, connector)


@router.get("/{connector_id}", response_model=ConnectorOut, summary="Détail d'un connecteur")
async def get_connector(connector_id: uuid.UUID, access: ViewerAccess, session: SessionDep) -> ConnectorOut:
    return await _one(session, await _load(session, access, connector_id))


@router.patch("/{connector_id}", response_model=ConnectorOut, summary="Modifier un connecteur")
async def update_connector(
    connector_id: uuid.UUID, body: ConnectorPatch, access: OwnerAccess, session: SessionDep
) -> ConnectorOut:
    connector = await _load(session, access, connector_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise validation_error("Aucune modification fournie")
    if body.config is not None:
        config = service.validate_config(connector.type, body.config, require_scope=True)
        await service.check_base_url(connector.type, config)
        if config != connector.config:
            connector.config = config
            connector.cursor = {}  # new scope or endpoint: next sync re-lists everything
    if body.secret is not None:
        connector.secret_ciphertext = secrets.encrypt(body.secret)
        connector.secret_hint = secrets.hint(body.secret)
    if body.name is not None:
        connector.name = body.name
    if body.schedule_minutes is not None:
        connector.schedule_minutes = body.schedule_minutes
    if body.default_classification is not None:
        connector.default_classification = body.default_classification
    if body.restrict_to_editors is not None:
        connector.restrict_to_editors = body.restrict_to_editors
    if body.paused is not None:
        if body.paused:
            connector.status = "paused"
        elif connector.status == "paused":
            connector.status = (
                "error" if connector.last_error else ("ok" if connector.last_sync_at else "idle")
            )
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        service.Action.update,
        "connector",
        connector.id,
        summary=f"Connecteur « {connector.name} » modifié",
        details={"fields": sorted(changes)},  # never the secret itself
    )
    await session.commit()
    await session.refresh(connector)
    return await _one(session, connector)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un connecteur")
async def delete_connector(connector_id: uuid.UUID, access: OwnerAccess, session: SessionDep) -> None:
    connector = await _load(session, access, connector_id)
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        service.Action.delete,
        "connector",
        connector.id,
        summary=f"Connecteur « {connector.name} » supprimé (documents déjà synchronisés conservés)",
        details={
            "type": connector.type,
            "source_id": str(connector.source_id) if connector.source_id else None,
        },
    )
    await session.delete(connector)
    await session.commit()


@router.post(
    "/{connector_id}/test", response_model=ConnectorTestOut, summary="Tester un connecteur enregistré"
)
async def test_connector(
    connector_id: uuid.UUID, access: OwnerAccess, session: SessionDep, body: ConnectorRetestIn | None = None
) -> ConnectorTestOut:
    connector = await _load(session, access, connector_id)
    body = body or ConnectorRetestIn()
    config = (
        service.validate_config(connector.type, body.config, require_scope=False)
        if body.config is not None
        else dict(connector.config or {})
    )
    await service.check_base_url(connector.type, config)
    if body.secret is not None:
        impl = service.instantiate(connector.type, config, body.secret)
    else:
        if not connector.secret_ciphertext:
            raise validation_error("Secret du connecteur absent : ressaisissez-le")
        impl = service.instantiate(connector.type, config, secrets.decrypt(connector.secret_ciphertext))
    result = await _run_test(impl)
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        service.Action.test,
        "connector",
        connector.id,
        summary=f"Test du connecteur « {connector.name} » : {'réussi' if result.ok else 'échec'}",
        details={"ok": result.ok},
    )
    await session.commit()
    return result


@router.post(
    "/{connector_id}/sync",
    response_model=ConnectorRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lancer une synchronisation",
)
async def sync_connector(
    connector_id: uuid.UUID, access: EditorAccess, session: SessionDep
) -> ConnectorRunOut:
    connector = await _load(session, access, connector_id)
    secrets.require_encryption()
    if await service.active_run(session, connector.id) is not None:
        raise conflict("Une synchronisation de ce connecteur est déjà en cours")
    actor = access.principal.actor
    trigger = "initial" if connector.last_sync_at is None else "manual"
    run = await service.request_sync(session, connector, trigger, actor)
    await audit.record(
        session,
        access.project_id,
        actor,
        service.Action.sync_requested,
        "connector",
        connector.id,
        summary=f"Synchronisation du connecteur « {connector.name} » demandée",
        details={"run_id": str(run.id), "trigger": trigger},
    )
    await session.commit()
    await session.refresh(run)
    return ConnectorRunOut.model_validate(run)


@router.get(
    "/{connector_id}/runs", response_model=Page[ConnectorRunOut], summary="Historique des synchronisations"
)
async def list_runs(
    connector_id: uuid.UUID,
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
) -> Page[ConnectorRunOut]:
    connector = await _load(session, access, connector_id)
    where = ConnectorRun.connector_id == connector.id
    total = await session.scalar(select(func.count()).select_from(ConnectorRun).where(where))
    rows = await session.scalars(
        select(ConnectorRun)
        .where(where)
        .order_by(ConnectorRun.created_at.desc())
        .offset(params.offset)
        .limit(params.page_size)
    )
    return make_page([ConnectorRunOut.model_validate(r) for r in rows], int(total or 0), params)


@router.get(
    "/{connector_id}/runs/{run_id}", response_model=ConnectorRunOut, summary="Détail d'une synchronisation"
)
async def get_run(
    connector_id: uuid.UUID, run_id: uuid.UUID, access: ViewerAccess, session: SessionDep
) -> ConnectorRunOut:
    connector = await _load(session, access, connector_id)
    run = await session.get(ConnectorRun, run_id)
    if run is None or run.connector_id != connector.id:
        raise not_found("Synchronisation introuvable")
    return ConnectorRunOut.model_validate(run)
