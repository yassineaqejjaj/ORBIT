"""OIDC relying party endpoints (NOV-109): ``/auth/oidc/*``. Each route is a 404 unless OIDC is enabled.

* ``GET  /auth/oidc/login``: redirects to the IdP (Authorization Code + PKCE S256, state, nonce);
* ``GET  /auth/oidc/callback``: a linked subject gets the ORBIT session cookie; an unknown subject
  with a verified e-mail that matches a local account of the same workspace gets ``202`` and a
  *link token* (nothing is linked yet); anything else is ``403``;
* ``POST /auth/oidc/link/confirm``: the user confirms with the local password; the link is created
  and the session opened (the only way to link, besides the explicit auto-provisioning flag);
* ``GET/DELETE /auth/oidc/identity``: the caller's own linked identity / unlinking it (password
  login is unaffected).
"""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import Field
from sqlalchemy import delete, select

from app import orion_claims
from app.api.auth import _client_ip, set_session_cookie
from app.config import settings
from app.db import utcnow
from app.deps import CurrentUser, SessionDep
from app.errors import ApiError, forbidden, not_found, unauthorized
from app.models import ExternalIdentity, User, Workspace
from app.schemas import User as UserOut
from app.schemas.common import ApiModel, InputModel
from app.security import create_access_token, verify_password
from app.services import audit
from app.services import oidc as oidc_service
from app.services import users as user_service
from app.services.audit import Actor, AuditAction

logger = logging.getLogger("orbit.oidc")

router = APIRouter(prefix="/auth/oidc", tags=["auth"])

COOKIE_PATH = "/api/v1/auth/oidc"
NO_ACCOUNT = "Aucun compte ORBIT ne correspond à cette identité SSO — contactez un administrateur"


def _require_enabled() -> None:
    if not settings.oidc_enabled:
        raise not_found("SSO désactivé")


class LinkConfirmIn(InputModel):
    link_token: str = Field(min_length=20, max_length=4000)
    password: str = Field(min_length=1, max_length=256)


class LinkRequired(ApiModel):
    status: str = "link_required"
    link_token: str
    expires_in: int
    email: str | None = None


class IdentityOut(ApiModel):
    issuer: str
    linked_by: str
    created_at: str
    last_login_at: str | None = None


def _mask(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


async def _open_session(session: SessionDep, user: User, request: Request, *, how: str) -> JSONResponse:
    """Audit the SSO login, then answer with the account and the usual ORBIT session cookie."""
    user.last_login_at = utcnow()
    await audit.record(
        session,
        None,
        user,
        AuditAction.auth_sso_login,
        "user",
        user.id,
        summary=f"Connexion SSO de {user.full_name}",
        details={"ip": _client_ip(request), "how": how},
    )
    await session.commit()
    response = JSONResponse(UserOut.model_validate(user).model_dump(mode="json"))
    set_session_cookie(response, create_access_token(user.id, password_hash=user.password_hash))
    response.delete_cookie(oidc_service.FLOW_COOKIE_NAME, path=COOKIE_PATH)
    return response


async def _refuse(
    session: SessionDep, request: Request, why: str, claims: orion_claims.Claims | None
) -> ApiError:
    await audit.record(
        session,
        None,
        Actor.system(),
        AuditAction.auth_sso_refused,
        "user",
        None,
        summary="Connexion SSO refusée",
        details={"why": why, "ip": _client_ip(request), "sub": claims.subject if claims else None},
    )
    await session.commit()
    return forbidden(NO_ACCOUNT)


@router.get("/login", summary="Connexion SSO (redirige vers le fournisseur d'identité)")
async def login() -> RedirectResponse:
    _require_enabled()
    if not settings.oidc_redirect_uri:
        raise ApiError(503, "ORBIT_OIDC_REDIRECT_URI n'est pas configuré", code="unavailable")
    cookie, state = oidc_service.new_flow()
    try:
        url = await oidc_service.authorization_url(cookie, state)
    except oidc_service.OidcUnavailable as exc:
        logger.warning("OIDC discovery failed: %s", exc)
        raise ApiError(
            503, "Fournisseur d'identité indisponible, réessayez plus tard", code="unavailable"
        ) from exc
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        oidc_service.FLOW_COOKIE_NAME,
        cookie,
        max_age=oidc_service.FLOW_TTL_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )
    return response


@router.get("/callback", summary="Retour du fournisseur d'identité (code d'autorisation + PKCE)")
async def callback(
    request: Request,
    session: SessionDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    flow: Annotated[str | None, Cookie(alias=oidc_service.FLOW_COOKIE_NAME)] = None,
) -> Response:
    _require_enabled()
    payload = oidc_service.read_flow(flow, state)
    if not code:
        raise unauthorized("Connexion SSO refusée par le fournisseur d'identité")
    access_token = await oidc_service.exchange_code(code, str(payload["cv"]))
    try:
        claims = await oidc_service.validate_access_token(access_token)
    except orion_claims.ClaimsError as exc:
        raise oidc_service._refusal(exc) from exc
    except oidc_service.OidcUnavailable as exc:
        raise oidc_service._unavailable(exc) from exc
    if claims.is_service or claims.workspace_id is None:
        raise await _refuse(session, request, "service_or_no_workspace", claims)

    identity = await oidc_service.find_identity(session, claims)
    user = await session.get(User, identity.user_id) if identity else None
    if identity is not None and user is not None:
        if str(user.workspace_id) != claims.workspace_id:
            raise await _refuse(session, request, "workspace_mismatch", claims)
        identity.last_login_at = utcnow()
        return await _open_session(session, user, request, how="linked")

    candidate = await oidc_service.candidate_user(session, claims)
    if candidate is None and settings.oidc_auto_provision and claims.email_matchable:
        provisioned = await _auto_provision(session, claims)
        if provisioned is not None:
            return await _open_session(session, provisioned, request, how="auto_provision")
    if candidate is None:
        raise await _refuse(session, request, "no_matching_account", claims)

    response = JSONResponse(
        LinkRequired(
            link_token=oidc_service.create_link_token(claims, candidate),
            expires_in=oidc_service.LINK_TTL_SECONDS,
            email=_mask(claims.email),
        ).model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED,
    )
    response.delete_cookie(oidc_service.FLOW_COOKIE_NAME, path=COOKIE_PATH)
    return response


async def _auto_provision(session: SessionDep, claims: orion_claims.Claims) -> User | None:
    """Auto-provisioning only: a C1 account without a usable password, in the token's workspace."""
    email = (claims.email or "").strip().lower()
    if (
        not email
        or claims.workspace_id is None
        or await user_service.get_by_email(session, email) is not None
    ):
        return None
    workspace_id = uuid.UUID(claims.workspace_id)
    if await session.get(Workspace, workspace_id) is None:
        return None  # the workspace must exist locally: provisioning never creates a space
    user = await user_service.create_user(
        session,
        email=email,
        full_name=claims.name or email,
        password=secrets.token_urlsafe(48),  # never shown, never used: the account signs in through the IdP
        clearance=1,
        is_admin=False,
        workspace_id=workspace_id,
    )
    await oidc_service.link(session, user, claims, linked_by="auto_provision")
    await audit.record(
        session,
        None,
        Actor.system(),
        AuditAction.auth_sso_link,
        "user",
        user.id,
        summary=f"Compte {user.email} créé et lié par SSO",
        details={"issuer": claims.issuer, "linked_by": "auto_provision"},
    )
    return user


@router.post("/link/confirm", response_model=UserOut, summary="Confirmer la liaison SSO (mot de passe local)")
async def confirm_link(body: LinkConfirmIn, request: Request, session: SessionDep) -> JSONResponse:
    _require_enabled()
    payload = oidc_service.read_link_token(body.link_token)
    oidc_service.count_link_attempt(str(payload["jti"]))
    user = await session.get(User, payload["uid"])
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok or str(user.workspace_id) != payload.get("ws"):
        await audit.record(
            session,
            None,
            Actor.system(),
            AuditAction.auth_sso_refused,
            "user",
            user.id if user else None,
            summary="Liaison SSO refusée (confirmation incorrecte)",
            details={"why": "bad_confirmation", "ip": _client_ip(request)},
        )
        await session.commit()
        raise unauthorized("Confirmation refusée : mot de passe incorrect")
    claims_like = orion_claims.Claims(
        subject=str(payload["idp_sub"]),
        issuer=str(payload["idp_iss"]),
        audience=(),
        issued_at=0,
        expires_at=0,
        email=payload.get("email"),
        email_verified=True,
        workspace_id=str(payload["ws"]),
    )
    taken = await session.scalar(
        select(ExternalIdentity.id).where(
            (ExternalIdentity.issuer == claims_like.issuer)
            & (ExternalIdentity.subject == claims_like.subject)
            | (ExternalIdentity.user_id == user.id) & (ExternalIdentity.issuer == claims_like.issuer)
        )
    )
    if taken is not None:
        raise ApiError(409, "Cette identité SSO ou ce compte est déjà lié", code="conflict")
    await oidc_service.link(session, user, claims_like, linked_by="confirmed")
    await audit.record(
        session,
        None,
        user,
        AuditAction.auth_sso_link,
        "user",
        user.id,
        summary=f"Liaison SSO confirmée par {user.full_name}",
        details={"issuer": claims_like.issuer, "linked_by": "confirmed", "ip": _client_ip(request)},
    )
    return await _open_session(session, user, request, how="link_confirmed")


@router.get("/identity", response_model=list[IdentityOut], summary="Identités SSO liées à mon compte")
async def my_identities(user: CurrentUser, session: SessionDep) -> list[IdentityOut]:
    _require_enabled()
    rows = await session.scalars(select(ExternalIdentity).where(ExternalIdentity.user_id == user.id))
    return [
        IdentityOut(
            issuer=r.issuer,
            linked_by=r.linked_by,
            created_at=r.created_at.isoformat(),
            last_login_at=r.last_login_at.isoformat() if r.last_login_at else None,
        )
        for r in rows
    ]


@router.delete("/identity", status_code=status.HTTP_204_NO_CONTENT, summary="Délier mon compte du SSO")
async def unlink(user: CurrentUser, session: SessionDep) -> Response:
    _require_enabled()
    await session.execute(delete(ExternalIdentity).where(ExternalIdentity.user_id == user.id))
    await audit.record(
        session,
        None,
        user,
        AuditAction.auth_sso_unlink,
        "user",
        user.id,
        summary=f"Liaison SSO supprimée par {user.full_name}",
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
