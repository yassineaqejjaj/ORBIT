"""Authentication: login (session cookie), logout, current user."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.config import settings
from app.db import utcnow
from app.deps import CurrentUser, SessionDep, get_optional_user
from app.errors import unauthorized
from app.schemas import LoginIn
from app.schemas import User as UserOut
from app.security import (
    SESSION_COOKIE_NAME,
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.services import audit
from app.services import users as user_service
from app.services.audit import Actor, AuditAction

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def set_session_cookie(response: Response, token: str, *, persistent: bool = True) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        # The JWT still expires after the session TTL; a non-persistent cookie also ends with the browser.
        max_age=settings.session_ttl_seconds if persistent else None,
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


@router.post("/login", response_model=UserOut, summary="Connexion (cookie de session)")
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep) -> UserOut:
    email = body.email.strip().lower()
    user = await user_service.get_by_email(session, email)
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok:
        await audit.record(
            session,
            None,
            Actor.system(),
            AuditAction.auth_login_failed,
            "user",
            user.id if user else None,
            summary=f"Échec de connexion pour {email}",
            details={"email": email, "ip": _client_ip(request)},
        )
        await session.commit()
        raise unauthorized("E-mail ou mot de passe incorrect")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = utcnow()
    await audit.record(
        session,
        None,
        user,
        AuditAction.auth_login,
        "user",
        user.id,
        summary=f"Connexion de {user.full_name}",
        details={"ip": _client_ip(request)},
    )
    await session.commit()

    token = create_access_token(user.id, password_hash=user.password_hash)
    set_session_cookie(response, token, persistent=body.remember)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Déconnexion")
async def logout(request: Request, session: SessionDep) -> Response:
    user = await get_optional_user(request, session)
    if user is not None:
        await audit.record(
            session,
            None,
            user,
            AuditAction.auth_logout,
            "user",
            user.id,
            summary=f"Déconnexion de {user.full_name}",
        )
        await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=UserOut, summary="Utilisateur connecté")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
