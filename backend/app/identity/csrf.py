"""CSRF protection (docs/PRODUCTION.md §0 « CSRF »): signed double submit + ``Origin``/``Referer`` check.

For every unsafe method (``POST``, ``PUT``, ``PATCH``, ``DELETE``) under ``/api/``:

* requests authenticated by ``Authorization: Bearer …`` or ``X-Orbit-Key`` are exempt (not sent
  automatically by browsers);
* when an ``Origin`` (or, failing that, ``Referer``) header is present it must be ``ORBIT_PUBLIC_URL``'s
  origin or the API's own origin — this also blocks login CSRF;
* when the request would be authenticated by the ``orbit_session`` cookie, the ``X-CSRF-Token``
  header must equal the ``orbit_csrf`` cookie and carry a valid signature bound to the session id.

Failures return ``403 {"detail": …, "code": "csrf_failed"}`` (the web client refreshes its token once).
"""

from __future__ import annotations

import hmac
import json
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.identity.netutil import is_secure_request
from app.security import (
    API_KEY_HEADER,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    csrf_token_valid,
    new_csrf_token,
    peek_session_id,
)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_FAILED_CODE = "csrf_failed"

MSG_ORIGIN = "Origine de la requête non autorisée (protection CSRF)."
MSG_TOKEN = "Jeton CSRF manquant ou invalide — rechargez la page puis réessayez."


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def allowed_origins(conn: HTTPConnection) -> set[str]:
    """``ORBIT_PUBLIC_URL`` and the API's own origin (Swagger, direct same-origin calls)."""
    origins = {settings.public_origin.lower()}
    host = conn.headers.get("host")
    if host:
        origins.add(f"{'https' if is_secure_request(conn) else 'http'}://{host.lower()}")
    return origins


def _has_explicit_credentials(conn: HTTPConnection) -> bool:
    if conn.headers.get(API_KEY_HEADER, "").strip():
        return True
    scheme, _, value = conn.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and bool(value.strip())


def csrf_failure(conn: HTTPConnection) -> str | None:
    """French reason to reject an unsafe request, ``None`` when it is acceptable."""
    if _has_explicit_credentials(conn):
        return None
    origin = conn.headers.get("origin")
    if origin is None and conn.headers.get("referer"):
        origin = _origin_of(conn.headers["referer"]) or "null"
    if origin is not None and origin.lower() not in allowed_origins(conn):
        return MSG_ORIGIN
    session_cookie = conn.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        return None
    session_id = peek_session_id(session_cookie)
    if session_id is None:
        return None  # expired/invalid cookie: the request is not authenticated by it
    header = conn.headers.get(CSRF_HEADER_NAME, "")
    cookie = conn.cookies.get(CSRF_COOKIE_NAME, "")
    if not header or not cookie or not hmac.compare_digest(header.encode(), cookie.encode()):
        return MSG_TOKEN
    if not csrf_token_valid(header, session_id):
        return MSG_TOKEN
    return None


def csrf_token_for(conn: HTTPConnection) -> str:
    """Current valid token of the caller, or a new one bound to its session (or anonymous)."""
    session_cookie = conn.cookies.get(SESSION_COOKIE_NAME)
    binding = (peek_session_id(session_cookie) if session_cookie else None) or ""
    existing = conn.cookies.get(CSRF_COOKIE_NAME)
    if existing and csrf_token_valid(existing, binding):
        return existing
    return new_csrf_token(binding)


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=False,  # read by the web client and echoed in X-CSRF-Token
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(key=CSRF_COOKIE_NAME, secure=settings.cookie_secure, samesite="lax", path="/")


class CsrfMiddleware:
    """Pure ASGI middleware enforcing :func:`csrf_failure` on unsafe ``/api/`` requests."""

    def __init__(self, app: ASGIApp, *, path_prefix: str = "/api/") -> None:
        self.app = app
        self.path_prefix = path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] in SAFE_METHODS
            or not str(scope.get("path", "")).startswith(self.path_prefix)
        ):
            await self.app(scope, receive, send)
            return
        reason = csrf_failure(HTTPConnection(scope))
        if reason is None:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": reason, "code": CSRF_FAILED_CODE}, ensure_ascii=False).encode()
        response = Response(content=body, status_code=403, media_type="application/json")
        await response(scope, receive, send)
