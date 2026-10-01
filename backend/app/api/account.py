"""Self-service account endpoints: active sessions and password change (docs/PRODUCTION.md §3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status

from app.api.auth import clear_session_cookie, set_session_cookie
from app.config import settings
from app.db import utcnow
from app.deps import CurrentUser, SessionDep
from app.errors import ApiError, not_found
from app.identity import ratelimit
from app.identity import sessions as session_service
from app.identity.events import IdentityAuditAction
from app.identity.netutil import client_ip
from app.identity.passwords import enforce_password_policy
from app.identity.schemas import AccountPasswordIn, AccountSession
from app.models.identity import UserSession
from app.security import create_access_token, verify_password
from app.services import audit
from app.services import users as user_service

router = APIRouter(prefix="/account", tags=["account"])

MSG_PASSWORD_RATE = "Trop de tentatives de changement de mot de passe : réessayez dans {delay}."


def _current_session(request: Request) -> UserSession | None:
    return getattr(request.state, "user_session", None)


@router.get("/sessions", response_model=list[AccountSession], summary="Mes sessions actives")
async def list_sessions(request: Request, user: CurrentUser, session: SessionDep) -> list[AccountSession]:
    current = _current_session(request)
    rows = await session_service.list_active_sessions(session, user.id)
    return [
        AccountSession(
            id=row.id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            ip=row.ip,
            user_agent=row.user_agent,
            auth_method=row.auth_method,
            current=current is not None and row.id == current.id,
        )
        for row in rows
    ]


@router.delete(
    "/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Révoquer une de mes sessions"
)
async def revoke_session(
    session_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep
) -> Response:
    row = await session.get(UserSession, session_id)
    if row is None or row.user_id != user.id or not session_service.is_active(row):
        raise not_found("Session introuvable")
    await session_service.revoke_session(session, row.id, session_service.RevokeReason.user_revoked)
    await audit.record(
        session,
        None,
        user,
        IdentityAuditAction.session_revoke,
        "user",
        user.id,
        summary=f"Session révoquée par {user.full_name}",
        details={"session_id": str(row.id), "ip": client_ip(request)},
    )
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    current = _current_session(request)
    if current is not None and current.id == row.id:
        clear_session_cookie(response)
    return response


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Changer mon mot de passe (révoque mes autres sessions)",
)
async def change_password(
    body: AccountPasswordIn, request: Request, user: CurrentUser, session: SessionDep
) -> Response:
    if user.auth_provider != "local":
        raise ApiError(
            409,
            "Le mot de passe de ce compte est géré par le fournisseur d'identité (SSO).",
            code="oidc_managed",
        )
    await ratelimit.enforce(
        "password-change", str(user.id), settings.rate_limit_login, detail=MSG_PASSWORD_RATE
    )
    if not verify_password(body.current_password, user.password_hash):
        raise ApiError(403, "Mot de passe actuel incorrect.", code="invalid_password")
    enforce_password_policy(body.new_password, email=user.email, full_name=user.full_name)
    if verify_password(body.new_password, user.password_hash):
        raise ApiError(
            422, "Le nouveau mot de passe doit être différent de l'actuel.", code="password_reused"
        )
    current = _current_session(request)
    user_service.set_password(user, body.new_password)
    revoked = await session_service.revoke_user_sessions(
        session,
        user.id,
        session_service.RevokeReason.password_changed,
        keep=current.id if current is not None else None,
    )
    await audit.record(
        session,
        None,
        user,
        IdentityAuditAction.password_change,
        "user",
        user.id,
        summary=f"Mot de passe modifié par {user.full_name}",
        details={"ip": client_ip(request), "revoked_sessions": revoked},
    )
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if current is not None:
        # The password fingerprint changed: re-mint the current session's JWT (same sid, same expiry).
        remaining = int((current.expires_at - utcnow()).total_seconds())
        token = create_access_token(
            user.id, session_id=current.id, password_hash=user.password_hash, ttl_seconds=max(60, remaining)
        )
        set_session_cookie(response, token)
    return response
