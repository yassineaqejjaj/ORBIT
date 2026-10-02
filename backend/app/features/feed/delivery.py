"""Webhook delivery (job ``kind=webhook``): signed POST, retries through the job queue, auto-disable.

Headers: ``X-Orbit-Event``, ``X-Orbit-Delivery``, ``X-Orbit-Signature: sha256=<HMAC(secret, body)>``.
The destination is re-checked (anti-SSRF) before every attempt; redirects are never followed.
Each failed attempt increments ``webhooks.consecutive_failures``; a success resets it; reaching
``settings.webhook_max_failures`` disables the webhook (audited, visible in the settings).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import orjson
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.features.feed import security
from app.ingestion.queue import PermanentJobError, RetryableJobError
from app.models import IngestionJob
from app.models.features_feed import Webhook, WebhookDelivery
from app.services import audit

USER_AGENT = "ORBIT-Webhooks/1.0"
MAX_ERROR = 500
#: Test hook: an ``httpx`` transport replacing the network (``httpx.MockTransport``).
transport_override: httpx.AsyncBaseTransport | None = None


def encode(payload: dict[str, Any]) -> bytes:
    return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)


@dataclass(frozen=True, slots=True)
class Attempt:
    status_code: int | None
    error: str | None
    duration_ms: float
    #: Retrying cannot help (destination refused by the anti-SSRF check).
    permanent: bool = False


async def send(hook: Webhook, delivery: WebhookDelivery) -> Attempt:
    """POST the delivery; never raises for network or HTTP errors."""
    started = time.perf_counter()
    try:
        await security.check_destination(hook.url)
    except security.UnsafeUrlError as exc:
        return Attempt(None, str(exc), 0.0, permanent=True)
    secret = security.decrypt_secret(hook.secret_encrypted)
    body = encode(delivery.payload)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Orbit-Event": delivery.event_type,
        "X-Orbit-Delivery": str(delivery.id),
        "X-Orbit-Signature": security.sign(secret, body),
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.webhook_timeout_seconds, follow_redirects=False, transport=transport_override
        ) as client:
            response = await client.post(hook.url, content=body, headers=headers)
    except httpx.TimeoutException:
        return Attempt(None, f"Délai dépassé ({settings.webhook_timeout_seconds:.0f} s)", _ms(started))
    except httpx.HTTPError as exc:
        return Attempt(None, f"Erreur réseau : {type(exc).__name__}", _ms(started))
    if 200 <= response.status_code < 300:
        return Attempt(response.status_code, None, _ms(started))
    return Attempt(response.status_code, f"Réponse HTTP {response.status_code}", _ms(started))


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


async def record_attempt(
    session: AsyncSession,
    hook: Webhook,
    delivery: WebhookDelivery,
    attempt: Attempt,
    *,
    final: bool,
    count_failure: bool = True,
) -> None:
    now = utcnow()
    error = attempt.error
    delivery.attempts += 1
    delivery.response_status = attempt.status_code
    delivery.duration_ms = attempt.duration_ms
    delivery.error = error[:MAX_ERROR] if error else None
    hook.last_delivery_at = now
    if error is None:
        delivery.status = "succeeded"
        delivery.delivered_at = now
        hook.last_status = "succeeded"
        hook.consecutive_failures = 0
        return
    delivery.status = "failed" if final else "pending"
    hook.last_status = "failed"
    if not count_failure:
        return
    hook.consecutive_failures += 1
    if hook.enabled and hook.consecutive_failures >= settings.webhook_max_failures:
        hook.enabled = False
        hook.disabled_reason = (
            f"Désactivé automatiquement après {hook.consecutive_failures} échecs consécutifs ({error})"
        )
        delivery.status = "failed"
        await audit.record(
            session,
            hook.project_id,
            None,
            audit.AuditAction.webhook_disabled,
            "webhook",
            hook.id,
            summary=f"Webhook {hook.url} désactivé après {hook.consecutive_failures} échecs",
            details={"failures": hook.consecutive_failures, "last_error": error},
        )


async def handle_webhook(session: AsyncSession, job: IngestionJob) -> None:
    """Job handler. Delivery state is committed before raising so the worker's rollback keeps it."""
    delivery_id = uuid.UUID(str((job.payload or {}).get("delivery_id")))
    delivery = await session.get(WebhookDelivery, delivery_id)
    if delivery is None:
        return
    hook = await session.get(Webhook, delivery.webhook_id)
    if hook is None or not hook.enabled:
        delivery.status = "skipped"
        delivery.error = "Webhook désactivé : livraison abandonnée"
        return
    if delivery.status != "pending":
        return
    attempt = await send(hook, delivery)
    final = attempt.permanent or job.attempts >= job.max_attempts
    await record_attempt(session, hook, delivery, attempt, final=final)
    if attempt.error is None:
        return
    final = final or not hook.enabled
    if final:
        delivery.status = "failed"
    await session.commit()
    if final:
        raise PermanentJobError(attempt.error)
    raise RetryableJobError(attempt.error)
