"""OIDC relying party (ADR 001 §2, §4, §8, NOV-109). Inert unless ``ORBIT_OIDC_ENABLED=true``.

* **IdP bearer tokens** are validated with the shared claims contract (:mod:`app.orion_claims`,
  copied from NOVA): RS256 + JWKS (cached, refetched on an unknown ``kid`` so a key rotation needs
  no restart), ``iss``, ``aud=orbit``, ``exp``, ``nbf``. A valid token proves *who* calls and in
  *which workspace*; it grants nothing alone: the account is the **linked** local user
  (``external_identities``), the functional role stays the local project membership,
  ``effective_clearance = min(User.clearance, orion_clearance)`` and ``orbit-admin`` only counts
  for an account that is also a local administrator.
* **Authorization Code + PKCE** for the browser (``/auth/oidc/login`` then ``/callback``): the
  result is the usual ORBIT session cookie. State, nonce and PKCE verifier travel in a short-lived
  signed cookie (no server state).
* **Linking is confirmed, never automatic**: an unknown subject whose e-mail the IdP verified, and
  that matches a local account of the same workspace, gets a short-lived *link token*; the link is
  created only when the user proves the local account with its password
  (``POST /auth/oidc/link/confirm``). No account is created unless
  ``ORBIT_OIDC_AUTO_PROVISION=true``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import orion_claims
from app.config import settings
from app.errors import ApiError, forbidden, unauthorized
from app.models import ExternalIdentity, User
from app.security import JWT_ALGORITHM, JWT_ISSUER

logger = logging.getLogger("orbit.oidc")

#: Tests inject a ``httpx.MockTransport`` here (no network).
transport_override: httpx.AsyncBaseTransport | None = None
#: Tests pin the clock (the signed fixtures are valid around a fixed instant).
clock_override: float | None = None

FORCED_REFRESH_MIN_INTERVAL = 30.0  # seconds between two JWKS refetches triggered by an unknown kid
FLOW_COOKIE_NAME = "orbit_oidc_flow"
FLOW_TTL_SECONDS = 600
LINK_TTL_SECONDS = 600
MAX_LINK_ATTEMPTS = 5

_REFUSAL_MESSAGES: dict[str, str] = {
    "expired": "Jeton SSO expiré — reconnectez-vous",
    "not_yet_valid": "Jeton SSO pas encore valide",
    "invalid_issuer": "Jeton SSO d'un émetteur inconnu",
    "invalid_audience": "Jeton SSO destiné à un autre service",
}


class OidcUnavailable(Exception):
    """The IdP (discovery, JWKS, token endpoint) cannot be reached or answered garbage."""


@dataclass(frozen=True, slots=True)
class OidcContext:
    """What a validated IdP token contributed to one request (kept on ``request.state.oidc``)."""

    claims: orion_claims.Claims
    decision: orion_claims.Decision
    identity_id: uuid.UUID

    @property
    def project_id(self) -> uuid.UUID | None:
        return uuid.UUID(self.claims.project_id) if self.claims.project_id else None


def now() -> float:
    return clock_override if clock_override is not None else time.time()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.oidc_http_timeout_seconds, transport=transport_override)


# --- Discovery and JWKS (cached) ----------------------------------------------------------------------------


@dataclass
class _Cache:
    jwks: dict[str, Any] | None = None
    jwks_at: float = 0.0
    forced_at: float = 0.0
    discovery: dict[str, Any] | None = None
    discovery_at: float = 0.0


_cache = _Cache()


def reset_cache() -> None:
    global _cache
    _cache = _Cache()


async def _get_json(url: str) -> dict[str, Any]:
    try:
        async with _client() as client:
            response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcUnavailable(f"{type(exc).__name__} while reading {url.split('?')[0]}") from exc
    if not isinstance(data, dict):
        raise OidcUnavailable("unexpected IdP answer")
    return data


async def discovery() -> dict[str, Any]:
    if _cache.discovery is not None and now() - _cache.discovery_at < settings.oidc_jwks_cache_seconds:
        return _cache.discovery
    url = f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
    _cache.discovery, _cache.discovery_at = await _get_json(url), now()
    return _cache.discovery


async def _endpoint(setting: str, key: str) -> str:
    configured: str = getattr(settings, setting)
    if configured:
        return configured
    value = (await discovery()).get(key)
    if not isinstance(value, str) or not value:
        raise OidcUnavailable(f"the IdP does not advertise {key}")
    return value


async def jwks(*, force: bool = False) -> dict[str, Any]:
    """The IdP's public keys, cached ``ORBIT_OIDC_JWKS_CACHE_SECONDS``; ``force`` refetches (rate limited)."""
    moment = now()
    fresh = _cache.jwks is not None and moment - _cache.jwks_at < settings.oidc_jwks_cache_seconds
    if fresh and not force:
        assert _cache.jwks is not None
        return _cache.jwks
    if force and _cache.jwks is not None and moment - _cache.forced_at < FORCED_REFRESH_MIN_INTERVAL:
        return _cache.jwks  # a flood of unknown kids must not hammer the IdP
    if force:
        _cache.forced_at = moment
    _cache.jwks, _cache.jwks_at = await _get_json(await _endpoint("oidc_jwks_url", "jwks_uri")), moment
    return _cache.jwks


# --- Token validation
# ----------------------------------------------------------------------------------------


def peek_algorithm(token: str) -> str | None:
    """The JOSE ``alg`` of a compact token, without verifying anything (routing only)."""
    try:
        head = token.split(".", 1)[0]
        header = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
    except (ValueError, UnicodeDecodeError):
        return None
    alg = header.get("alg") if isinstance(header, dict) else None
    return alg if isinstance(alg, str) else None


def is_idp_token(token: str) -> bool:
    """Session tokens are HS256; with OIDC on, anything else is read as an IdP token (and refused if
    invalid)."""
    return settings.oidc_enabled and peek_algorithm(token) != JWT_ALGORITHM


async def validate_access_token(token: str) -> orion_claims.Claims:
    """Validate with the shared contract; an unknown ``kid`` triggers one JWKS refetch (key rotation)."""
    keys = await jwks()
    for attempt in (1, 2):
        try:
            return orion_claims.validate_token(
                token,
                keys,
                issuer=settings.oidc_issuer,
                audience=settings.oidc_audience,
                now=now(),
                leeway=settings.oidc_leeway_seconds,
            )
        except orion_claims.ClaimsError as exc:
            if exc.code == "unknown_key" and attempt == 1:
                refreshed = await jwks(force=True)
                if refreshed is not keys:
                    keys = refreshed
                    continue
            raise
    raise AssertionError("unreachable")  # pragma: no cover


def _refusal(exc: orion_claims.ClaimsError) -> ApiError:
    return unauthorized(_REFUSAL_MESSAGES.get(exc.code, "Jeton SSO invalide"))


def _unavailable(exc: OidcUnavailable) -> ApiError:
    logger.warning("OIDC provider unavailable: %s", exc)
    return ApiError(503, "Fournisseur d'identité indisponible, réessayez plus tard", code="unavailable")


async def find_identity(session: AsyncSession, claims: orion_claims.Claims) -> ExternalIdentity | None:
    return await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == claims.issuer, ExternalIdentity.subject == claims.subject
        )
    )


def _same_workspace(user: User, claims: orion_claims.Claims) -> bool:
    return claims.workspace_id is not None and str(user.workspace_id) == claims.workspace_id


async def authenticate_bearer(session: AsyncSession, token: str) -> tuple[User, OidcContext]:
    """The linked local user behind an IdP access token, with what the token contributes (never more than
    local)."""
    try:
        claims = await validate_access_token(token)
    except orion_claims.ClaimsError as exc:
        raise _refusal(exc) from exc
    except OidcUnavailable as exc:
        raise _unavailable(exc) from exc
    if claims.is_service:
        raise forbidden("Un compte de service s'authentifie avec une clé d'agent")
    if claims.workspace_id is None:
        raise forbidden("Jeton SSO sans espace : aucune ressource d'espace n'est accessible")
    identity = await find_identity(session, claims)
    user = await session.get(User, identity.user_id) if identity else None
    if identity is None or user is None:
        raise unauthorized("Compte SSO non lié à un compte ORBIT — liez-le via /auth/oidc/login")
    if not _same_workspace(user, claims):
        raise forbidden("L'espace du jeton ne correspond pas à celui du compte lié")
    decision = orion_claims.decide(claims, "orbit", local_clearance=int(user.clearance))
    return user, OidcContext(claims=claims, decision=decision, identity_id=identity.id)


# --- Browser flow: Authorization Code + PKCE
# ---------------------------------------------------------------------


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()


def new_flow() -> tuple[str, str]:
    """``(authorization_state_cookie_value, state)`` — the signed cookie carries state, nonce and verifier."""
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    payload = {
        "typ": "oidc-flow",
        "iss": JWT_ISSUER,
        "state": state,
        "nonce": nonce,
        "cv": verifier,
        "iat": int(now()),
        "exp": int(now()) + FLOW_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM), state


def read_flow(cookie: str | None, state: str | None) -> dict[str, Any]:
    if not cookie or not state:
        raise unauthorized("Connexion SSO invalide ou expirée — recommencez")
    try:
        payload = jwt.decode(
            cookie, settings.jwt_secret, algorithms=[JWT_ALGORITHM], issuer=JWT_ISSUER, leeway=0,
            options={"verify_exp": False, "verify_iat": False},
        )  # fmt: skip
    except jwt.PyJWTError as exc:
        raise unauthorized("Connexion SSO invalide ou expirée — recommencez") from exc
    if (
        payload.get("typ") != "oidc-flow"
        or int(payload.get("exp", 0)) < now()
        or not secrets.compare_digest(str(payload.get("state", "")), state)
    ):
        raise unauthorized("Connexion SSO invalide ou expirée — recommencez")
    return payload


async def authorization_url(flow_cookie: str, state: str) -> str:
    payload = jwt.decode(
        flow_cookie,
        settings.jwt_secret,
        algorithms=[JWT_ALGORITHM],
        options={"verify_exp": False, "verify_iat": False},
    )
    endpoint = await _endpoint("oidc_authorization_endpoint", "authorization_endpoint")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.oidc_redirect_uri,
            "scope": settings.oidc_scopes,
            "state": state,
            "nonce": payload["nonce"],
            "code_challenge": _pkce_challenge(payload["cv"]),
            "code_challenge_method": "S256",
        }
    )
    return f"{endpoint}{'&' if '?' in endpoint else '?'}{query}"


async def exchange_code(code: str, verifier: str) -> str:
    """Authorization code → access token (PKCE verifier; client secret only when one is configured)."""
    endpoint = await _endpoint("oidc_token_endpoint", "token_endpoint")
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": verifier,
    }
    if settings.oidc_client_secret:
        form["client_secret"] = settings.oidc_client_secret
    try:
        async with _client() as client:
            response = await client.post(endpoint, data=form, headers={"Accept": "application/json"})
        if response.status_code in (400, 401):
            raise unauthorized("Code d'autorisation SSO refusé")
        response.raise_for_status()
        access_token = response.json().get("access_token")
    except (httpx.HTTPError, ValueError) as exc:
        raise _unavailable(OidcUnavailable(type(exc).__name__)) from exc
    if not isinstance(access_token, str) or not access_token:
        raise _unavailable(OidcUnavailable("no access_token in the token response"))
    return access_token


# --- Linking
# ------------------------------------------------------------------------------------------------------


_link_attempts: dict[str, int] = {}


def create_link_token(claims: orion_claims.Claims, user: User) -> str:
    payload = {
        "typ": "oidc-link",
        "iss": JWT_ISSUER,
        "idp_iss": claims.issuer,
        "idp_sub": claims.subject,
        "uid": str(user.id),
        "ws": claims.workspace_id,
        "email": claims.email,
        "jti": secrets.token_hex(8),
        "iat": int(now()),
        "exp": int(now()) + LINK_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def read_link_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[JWT_ALGORITHM], issuer=JWT_ISSUER,
            options={"verify_exp": False, "verify_iat": False},
        )  # fmt: skip
    except jwt.PyJWTError as exc:
        raise unauthorized("Jeton de liaison invalide ou expiré") from exc
    if payload.get("typ") != "oidc-link" or int(payload.get("exp", 0)) < now():
        raise unauthorized("Jeton de liaison invalide ou expiré")
    return payload


def count_link_attempt(jti: str) -> None:
    """Best effort (per process): a link token tolerates a few wrong passwords, then is burnt."""
    _link_attempts[jti] = _link_attempts.get(jti, 0) + 1
    if _link_attempts[jti] > MAX_LINK_ATTEMPTS:
        raise forbidden("Trop de tentatives — recommencez la connexion SSO")
    if len(_link_attempts) > 10_000:
        _link_attempts.clear()


async def candidate_user(session: AsyncSession, claims: orion_claims.Claims) -> User | None:
    """The local account an unlinked subject may ask to link: verified e-mail, same workspace, not yet
    linked."""
    if not claims.email_matchable or claims.workspace_id is None or claims.email is None:
        return None
    user = await session.scalar(select(User).where(User.email == claims.email.strip().lower()))
    if user is None or not _same_workspace(user, claims):
        return None
    already = await session.scalar(
        select(ExternalIdentity.id).where(
            ExternalIdentity.user_id == user.id, ExternalIdentity.issuer == claims.issuer
        )
    )
    return None if already else user


async def link(
    session: AsyncSession, user: User, claims: orion_claims.Claims, *, linked_by: str
) -> ExternalIdentity:
    assert claims.workspace_id is not None
    identity = ExternalIdentity(
        user_id=user.id,
        workspace_id=uuid.UUID(claims.workspace_id),
        issuer=claims.issuer,
        subject=claims.subject,
        email=claims.email,
        linked_by=linked_by,
    )
    session.add(identity)
    await session.flush()
    return identity
