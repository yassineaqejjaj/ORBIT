"""Project webhooks (owner) — docs/FEATURES.md F2.

The signing secret is generated server side, stored encrypted (``ORBIT_ENCRYPTION_KEY``) and shown
once at creation. URLs must be HTTPS and resolve to public addresses (anti-SSRF), except when
``ORBIT_ENV=development``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.deps import OwnerAccess, ProjectAccess, SessionDep
from app.errors import not_found, validation_error
from app.features.feed import delivery as webhook_delivery
from app.features.feed import security
from app.features.feed.schemas import (
    WebhookCreated,
    WebhookDeliveryOut,
    WebhookIn,
    WebhookOut,
    WebhookPatch,
)
from app.features.feed.types import PING_TYPE
from app.models.features_feed import Webhook, WebhookDelivery
from app.schemas import Page, PageParams, page_params
from app.schemas.common import make_page
from app.services import audit

router = APIRouter(prefix="/projects/{slug}/webhooks", tags=["webhooks"])

NOT_FOUND = "Webhook introuvable"
MAX_WEBHOOKS = 20


async def _load(session: AsyncSession, access: ProjectAccess, webhook_id: uuid.UUID) -> Webhook:
    hook = await session.get(Webhook, webhook_id)
    if hook is None or hook.project_id != access.project_id:
        raise not_found(NOT_FOUND)
    return hook


async def _check_url(url: str) -> str:
    url = url.strip()
    try:
        await security.check_destination(url)
    except security.UnsafeUrlError as exc:
        raise validation_error(str(exc)) from exc
    return url


@router.get("", response_model=list[WebhookOut], summary="Webhooks du projet")
async def list_webhooks(access: OwnerAccess, session: SessionDep) -> list[WebhookOut]:
    rows = await session.scalars(
        select(Webhook).where(Webhook.project_id == access.project_id).order_by(Webhook.created_at)
    )
    return [WebhookOut.model_validate(row) for row in rows]


@router.post(
    "", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED, summary="Créer un webhook"
)
async def create_webhook(body: WebhookIn, access: OwnerAccess, session: SessionDep) -> WebhookCreated:
    secret = security.generate_secret()
    encrypted = security.encrypt_secret(secret)  # 503 when ORBIT_ENCRYPTION_KEY is missing
    url = await _check_url(body.url)
    existing = await session.scalars(select(Webhook.id).where(Webhook.project_id == access.project_id))
    if len(list(existing)) >= MAX_WEBHOOKS:
        raise validation_error(f"Nombre maximal de webhooks atteint ({MAX_WEBHOOKS})")
    hook = Webhook(
        project_id=access.project_id,
        url=url,
        description=body.description,
        types=body.types,
        secret_encrypted=encrypted,
        secret_hint=security.secret_hint(secret),
        enabled=True,
        consecutive_failures=0,
        created_by_id=access.principal.user_id,
    )
    session.add(hook)
    await session.flush()
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        audit.AuditAction.webhook_create,
        "webhook",
        hook.id,
        summary=f"Webhook créé vers {url}",
        details={"url": url, "types": body.types},
    )
    await session.commit()
    await session.refresh(hook)
    return WebhookCreated(**WebhookOut.model_validate(hook).model_dump(), secret=secret)


@router.patch("/{webhook_id}", response_model=WebhookOut, summary="Modifier un webhook")
async def update_webhook(
    webhook_id: uuid.UUID, body: WebhookPatch, access: OwnerAccess, session: SessionDep
) -> WebhookOut:
    hook = await _load(session, access, webhook_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise validation_error("Aucune modification fournie")
    if body.url is not None:
        hook.url = await _check_url(body.url)
    if body.types is not None:
        hook.types = body.types
    if body.description is not None:
        hook.description = body.description
    if body.enabled is not None:
        hook.enabled = body.enabled
        if body.enabled:
            hook.consecutive_failures = 0
            hook.disabled_reason = None
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        audit.AuditAction.webhook_update,
        "webhook",
        hook.id,
        summary=f"Webhook {hook.url} modifié",
        details={"fields": sorted(changes)},
    )
    await session.commit()
    await session.refresh(hook)
    return WebhookOut.model_validate(hook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un webhook")
async def delete_webhook(webhook_id: uuid.UUID, access: OwnerAccess, session: SessionDep) -> None:
    hook = await _load(session, access, webhook_id)
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        audit.AuditAction.webhook_delete,
        "webhook",
        hook.id,
        summary=f"Webhook {hook.url} supprimé",
        details={"url": hook.url},
    )
    await session.delete(hook)
    await session.commit()


@router.post("/{webhook_id}/test", response_model=WebhookDeliveryOut, summary="Envoyer un événement de test")
async def test_webhook(webhook_id: uuid.UUID, access: OwnerAccess, session: SessionDep) -> WebhookDeliveryOut:
    """Synchronous ``ping`` delivery (not retried, not counted towards auto-disable)."""
    hook = await _load(session, access, webhook_id)
    delivery = WebhookDelivery(
        webhook_id=hook.id,
        project_id=hook.project_id,
        event_type=PING_TYPE,
        status="pending",
        attempts=0,
        payload={
            "id": str(uuid.uuid4()),
            "type": PING_TYPE,
            "project": {"id": str(access.project_id), "slug": access.project.slug},
            "title": "Test de webhook ORBIT",
            "summary": "Événement de test envoyé depuis les paramètres du projet",
            "created_at": utcnow().isoformat(),
            "restricted": False,
        },
    )
    session.add(delivery)
    await session.flush()
    attempt = await webhook_delivery.send(hook, delivery)
    await webhook_delivery.record_attempt(session, hook, delivery, attempt, final=True, count_failure=False)
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        audit.AuditAction.webhook_test,
        "webhook",
        hook.id,
        summary=f"Test du webhook {hook.url} : {'succès' if attempt.error is None else 'échec'}",
        details={"status": attempt.status_code, "error": attempt.error},
    )
    await session.commit()
    await session.refresh(delivery)
    return WebhookDeliveryOut.model_validate(delivery)


@router.get(
    "/{webhook_id}/deliveries", response_model=Page[WebhookDeliveryOut], summary="Historique des livraisons"
)
async def list_deliveries(
    webhook_id: uuid.UUID,
    access: OwnerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    status_: str | None = Query(default=None, alias="status", pattern="^(pending|succeeded|failed|skipped)$"),
) -> Page[WebhookDeliveryOut]:
    hook = await _load(session, access, webhook_id)
    from sqlalchemy import func

    conditions = [WebhookDelivery.webhook_id == hook.id]
    if status_:
        conditions.append(WebhookDelivery.status == status_)
    total = await session.scalar(select(func.count()).select_from(WebhookDelivery).where(*conditions))
    rows = await session.scalars(
        select(WebhookDelivery)
        .where(*conditions)
        .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id)
        .offset(params.offset)
        .limit(params.limit)
    )
    return make_page([WebhookDeliveryOut.model_validate(r) for r in rows], int(total or 0), params)


__all__ = ["router"]
