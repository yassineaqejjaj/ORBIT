"""Change feed & subscriptions (docs/FEATURES.md F2).

Events are filtered by rights (classification ≤ clearance, ACL ∩ principals) exactly like the
context engine; private user memory never produces events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.context import snapshots as snapshot_service
from app.deps import SessionDep, ViewerAccess
from app.errors import not_found, validation_error
from app.features.feed import service
from app.features.feed.schemas import ChangeEventOut, Digest, SinceSnapshot, SubscriptionIn, SubscriptionOut
from app.features.feed.types import normalize_types
from app.models.features_feed import Subscription
from app.schemas import Page, PageParams, page_params
from app.schemas.common import make_page
from app.services import audit

router = APIRouter(prefix="/projects/{slug}", tags=["feed"])


def _types(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return normalize_types([value for value in raw.split(",") if value.strip()])
    except ValueError as exc:
        raise validation_error(str(exc)) from exc


@router.get(
    "/changes", response_model=Page[ChangeEventOut], summary="Fil des changements (filtré par droits)"
)
async def list_changes(
    access: ViewerAccess,
    session: SessionDep,
    params: Annotated[PageParams, Depends(page_params)],
    since: datetime | None = Query(default=None, description="Changements postérieurs à cette date"),
    types: str | None = Query(default=None, description="Types séparés par des virgules"),
) -> Page[ChangeEventOut]:
    viewer = service.FeedViewer.from_access(access)
    rows, total = await service.list_changes(
        session, viewer, since=since, types=_types(types), offset=params.offset, limit=params.limit
    )
    return make_page([service.to_out(row) for row in rows], total, params)


@router.get(
    "/changes/since-snapshot",
    response_model=SinceSnapshot,
    summary="Changements depuis une version de snapshot",
)
async def changes_since_snapshot(
    access: ViewerAccess,
    session: SessionDep,
    name: str = Query(min_length=1, max_length=200),
    version: str = Query(default="latest"),
) -> SinceSnapshot:
    parsed = snapshot_service.parse_version(version)
    snapshot = await snapshot_service.get_snapshot(session, access.project_id, name, parsed)
    if snapshot is None:
        raise not_found("Snapshot introuvable")
    return await service.since_snapshot(session, access, snapshot)


@router.get("/changes/digest", response_model=Digest, summary="Résumé des changements (jour / semaine)")
async def changes_digest(
    access: ViewerAccess,
    session: SessionDep,
    period: Literal["day", "week"] = Query(default="day"),
) -> Digest:
    subscription = await _subscription(session, access)
    return await service.build_digest(
        session,
        service.FeedViewer.from_access(access),
        period,
        types=(subscription.types or None) if subscription else None,
        project_name=access.project.name,
    )


async def _subscription(session: SessionDep, access: ViewerAccess) -> Subscription | None:
    assert access.principal.user_id is not None
    return await session.scalar(
        select(Subscription).where(
            Subscription.project_id == access.project_id, Subscription.user_id == access.principal.user_id
        )
    )


def _subscription_out(subscription: Subscription | None) -> SubscriptionOut:
    if subscription is None:
        return SubscriptionOut(digest="off", types=[], email_enabled=service.smtp_configured())
    return SubscriptionOut(
        digest=subscription.digest,  # type: ignore[arg-type]
        types=list(subscription.types or []),
        last_digest_at=subscription.last_digest_at,
        email_enabled=service.smtp_configured(),
    )


@router.get("/subscriptions/me", response_model=SubscriptionOut, summary="Mon abonnement au fil")
async def get_my_subscription(access: ViewerAccess, session: SessionDep) -> SubscriptionOut:
    return _subscription_out(await _subscription(session, access))


@router.put("/subscriptions/me", response_model=SubscriptionOut, summary="Modifier mon abonnement")
async def put_my_subscription(
    body: SubscriptionIn, access: ViewerAccess, session: SessionDep
) -> SubscriptionOut:
    subscription = await _subscription(session, access)
    if subscription is None:
        assert access.principal.user_id is not None
        subscription = Subscription(project_id=access.project_id, user_id=access.principal.user_id)
        session.add(subscription)
    subscription.digest = body.digest
    subscription.types = body.types
    await audit.record(
        session,
        access.project_id,
        access.principal.actor,
        audit.AuditAction.subscription_update,
        "subscription",
        access.principal.user_id,
        summary=f"Abonnement au fil : résumé {body.digest}",
        details={"digest": body.digest, "types": body.types},
    )
    await session.commit()
    await session.refresh(subscription)
    return _subscription_out(subscription)


__all__ = ["router"]
