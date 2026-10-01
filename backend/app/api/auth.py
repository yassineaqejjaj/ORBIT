"""Authentication: login (server-side session + cookie), forced password change, logout, CSRF, config.

Login is rate limited per (IP, e-mail) with ``ORBIT_RATE_LIMIT_LOGIN`` and per IP with ten times that
limit; consecutive failures lock the account progressively (``ORBIT_LOGIN_LOCKOUT_*``).
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import utcnow
from app.deps import CurrentUser, SessionDep, get_optional_user
from app.errors import ApiError, unauthorized
from app.identity import ratelimit
from app.identity import sessions as session_service
from app.identity.csrf import clear_csrf_cookie, csrf_token_for, set_csrf_cookie
from app.identity.events import IdentityAuditAction
from app.identity.netutil import client_ip
from app.identity.passwords import enforce_password_policy
from app.identity.schemas import (
    AuthConfig,
    CsrfOut,
    OidcConfig,
    PasswordChangeChallenge,
    PasswordChangeRequiredIn,
    UserOut,
)
from app.models import User
from app.schemas import LoginIn
from app.schemas.common import normalize_email
from app.security import (
    SESSION_COOKIE_NAME,
    TokenError,
    create_purpose_token,
    decode_purpose_token,
    hash_password,
    new_csrf_token,
    password_fingerprint,
    password_needs_rehash,
    verify_password,
)
from app.services import audit
from app.services import users as user_service
from app.services.audit import Actor, AuditAction

router = APIRouter(prefix="/auth", tags=["auth"])

#: The per-IP login window is this many times ``ORBIT_RATE_LIMIT_LOGIN`` (users behind a shared NAT).
LOGIN_IP_FACTOR = 10
#: Lifetime of the token returned when the password must be changed before a session is opened.
PASSWORD_CHANGE_TOKEN_TTL_SECONDS = 600
PASSWORD_CHANGE_PURPOSE = "password_change"

MSG_BAD_CREDENTIALS = "E-mail ou mot de passe incorrect"
MSG_LOGIN_RATE = "Trop de tentatives de connexion : réessayez dans {delay}."
MSG_LOCKED = "Compte temporairement verrouillé après plusieurs échecs : réessayez dans {delay}."


# --- Cookies ----------------------------------------------------------------------------------------


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def start_session_cookies(response: Response, issued: session_service.IssuedSession) -> None:
    """Session cookie + a CSRF token bound to the new session id (also used by OIDC / invitations)."""
    set_session_cookie(response, issued.token)
    set_csrf_cookie(response, new_csrf_token(str(issued.row.id)))


async def open_session(
    db: AsyncSession,
    user: User,
    request: Request,
    response: Response,
    method: session_service.AuthMethod,
) -> session_service.IssuedSession:
    """Create the server-side session, audit ``auth.login``, commit and set the cookies."""
    user.last_login_at = utcnow()
    issued = await session_service.create_session(db, user, conn=request, method=method)
    await audit.record(
        db,
        None,
        user,
        AuditAction.auth_login,
        "user",
        user.id,
        summary=f"Connexion de {user.full_name}",
        details={"ip": issued.row.ip, "session_id": str(issued.row.id), "method": method.value},
    )
    await db.commit()
    start_session_cookies(response, issued)
    return issued


# --- Endpoints ----------------------------------------------------------------------------------------


@router.get("/config", response_model=AuthConfig, summary="Modes de connexion disponibles")
async def auth_config() -> AuthConfig:
    return AuthConfig(
        local_login=settings.local_login_enabled,
        oidc=OidcConfig(enabled=settings.oidc_enabled, label=settings.oidc_label),
        mfa_policy=settings.mfa_required,
        password_min_length=settings.password_min_length,
    )


@router.get("/csrf", response_model=CsrfOut, summary="Jeton CSRF (double soumission)")
async def csrf(request: Request, response: Response) -> CsrfOut:
    token = csrf_token_for(request)
    set_csrf_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return CsrfOut(csrf_token=token)


def _login_identity(ip: str, email: str) -> str:
    return hashlib.sha256(f"{ip}|{email}".encode()).hexdigest()[:32]


async def _record_failure(
    db: AsyncSession, request: Request, email: str, user: User | None, reason: str
) -> None:
    locked_for = await ratelimit.register_failure(
        email,
        threshold=settings.login_lockout_threshold,
        base_seconds=settings.login_lockout_base_seconds,
        max_seconds=settings.login_lockout_max_seconds,
    )
    ip = client_ip(request)
    await audit.record(
        db,
        None,
        Actor.system(),
        AuditAction.auth_login_failed,
        "user",
        user.id if user else None,
        summary=f"Échec de connexion pour {email}",
        details={"email": email, "ip": ip, "reason": reason},
    )
    if locked_for > 0:
        await audit.record(
            db,
            None,
            Actor.system(),
            IdentityAuditAction.login_locked,
            "user",
            user.id if user else None,
            summary=f"Compte {email} verrouillé {int(locked_for)} s après des échecs répétés",
            details={"email": email, "ip": ip, "locked_seconds": int(locked_for)},
        )
    await db.commit()
    if locked_for > 0:
        raise ratelimit.RateLimited(locked_for, MSG_LOCKED, code="account_locked")


@router.post(
    "/login",
    response_model=UserOut | PasswordChangeChallenge,
    summary="Connexion (cookie de session)",
    responses={429: {"description": "Trop de tentatives ou compte verrouillé (en-tête Retry-After)"}},
)
async def login(
    body: LoginIn, request: Request, response: Response, session: SessionDep
) -> UserOut | PasswordChangeChallenge:
    if not settings.local_login_enabled:
        raise ApiError(
            403,
            "La connexion par mot de passe est désactivée : utilisez le SSO.",
            code="local_login_disabled",
        )
    email = normalize_email(body.email)
    ip = client_ip(request) or "unknown"
    await ratelimit.enforce(
        "login-ip", ip, ratelimit.scaled(settings.rate_limit_login, LOGIN_IP_FACTOR), detail=MSG_LOGIN_RATE
    )
    await ratelimit.enforce(
        "login", _login_identity(ip, email), settings.rate_limit_login, detail=MSG_LOGIN_RATE
    )
    locked = await ratelimit.lockout_remaining(email)
    if locked > 0:
        raise ratelimit.RateLimited(locked, MSG_LOCKED, code="account_locked")

    user = await user_service.get_by_email(session, email)
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok or user.auth_provider != "local":
        await _record_failure(session, request, email, user, "bad_credentials")
        raise unauthorized(MSG_BAD_CREDENTIALS)
    if not user.is_active:
        await _record_failure(session, request, email, user, "deactivated")
        raise ApiError(403, "Compte désactivé — contactez un administrateur.", code="account_disabled")

    await ratelimit.register_success(email)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    if user.must_change_password:
        await audit.record(
            session,
            None,
            user,
            IdentityAuditAction.password_change_required,
            "user",
            user.id,
            summary=f"Changement de mot de passe exigé pour {user.full_name}",
            details={"ip": ip},
        )
        await session.commit()
        token = create_purpose_token(
            PASSWORD_CHANGE_PURPOSE,
            str(user.id),
            ttl_seconds=PASSWORD_CHANGE_TOKEN_TTL_SECONDS,
            extra={"pwf": password_fingerprint(user.password_hash)},
        )
        return PasswordChangeChallenge(change_token=token)

    await open_session(session, user, request, response, session_service.AuthMethod.password)
    return UserOut.model_validate(user)


@router.post(
    "/password/change-required",
    response_model=UserOut,
    summary="Changement de mot de passe obligatoire (première connexion, réinitialisation)",
)
async def change_required_password(
    body: PasswordChangeRequiredIn, request: Request, response: Response, session: SessionDep
) -> UserOut:
    invalid = ApiError(
        401,
        "Jeton de changement de mot de passe invalide ou expiré — reconnectez-vous.",
        code="invalid_token",
    )
    try:
        payload = decode_purpose_token(body.change_token, PASSWORD_CHANGE_PURPOSE)
        user_id = uuid.UUID(str(payload["sub"]))
    except (TokenError, ValueError) as exc:
        raise invalid from exc
    user = await session.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or not user.must_change_password
        or payload.get("pwf") != password_fingerprint(user.password_hash)
    ):
        raise invalid
    enforce_password_policy(body.new_password, email=user.email, full_name=user.full_name)
    if verify_password(body.new_password, user.password_hash):
        raise ApiError(
            422, "Le nouveau mot de passe doit être différent de l'actuel.", code="password_reused"
        )
    user_service.set_password(user, body.new_password)
    await session_service.revoke_user_sessions(
        session, user.id, session_service.RevokeReason.password_changed
    )
    await audit.record(
        session,
        None,
        user,
        IdentityAuditAction.password_change,
        "user",
        user.id,
        summary=f"Mot de passe modifié par {user.full_name} (changement obligatoire)",
        details={"ip": client_ip(request), "forced": True},
    )
    await open_session(session, user, request, response, session_service.AuthMethod.password_change)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Déconnexion (révoque la session)")
async def logout(request: Request, session: SessionDep) -> Response:
    user = await get_optional_user(request, session)
    current = getattr(request.state, "user_session", None)
    if user is not None:
        if current is not None:
            await session_service.revoke_session(session, current.id, session_service.RevokeReason.logout)
        await audit.record(
            session,
            None,
            user,
            AuditAction.auth_logout,
            "user",
            user.id,
            summary=f"Déconnexion de {user.full_name}",
            details={"session_id": str(current.id) if current is not None else None},
        )
        await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    return response


@router.get("/me", response_model=UserOut, summary="Utilisateur connecté")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
