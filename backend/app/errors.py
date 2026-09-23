"""Uniform error format ``{"detail": "<message FR>", "code": "<code>"}`` and exception handlers.

Routers raise :class:`ApiError` (or one of the helpers ``not_found()``, ``forbidden()``, ...).
Plain ``HTTPException`` and validation errors are converted to the same shape.
``NotImplementedError`` becomes ``501 not_implemented``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability.context import get_request_id

logger = logging.getLogger("orbit.errors")

STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    501: "not_implemented",
    502: "bad_gateway",
    503: "unavailable",
}

DEFAULT_MESSAGES: dict[int, str] = {
    400: "Requête invalide",
    401: "Authentification requise",
    403: "Accès refusé",
    404: "Ressource introuvable",
    405: "Méthode non autorisée",
    409: "Conflit avec l'état actuel de la ressource",
    413: "Contenu trop volumineux",
    415: "Type de contenu non pris en charge",
    422: "Données invalides",
    429: "Trop de requêtes, réessayez plus tard",
    500: "Erreur interne du serveur",
    501: "Fonctionnalité non disponible",
    503: "Service temporairement indisponible",
}


class ApiError(HTTPException):
    """HTTP error carrying a stable machine-readable ``code``."""

    def __init__(
        self,
        status_code: int,
        detail: str | None = None,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            detail=detail or DEFAULT_MESSAGES.get(status_code, "Erreur"),
            headers=headers,
        )
        self.code = code or STATUS_CODES.get(status_code, "error")


def bad_request(detail: str = DEFAULT_MESSAGES[400]) -> ApiError:
    return ApiError(400, detail, code="bad_request")


def unauthorized(detail: str = DEFAULT_MESSAGES[401]) -> ApiError:
    return ApiError(401, detail, code="unauthorized", headers={"WWW-Authenticate": "Bearer"})


def forbidden(detail: str = DEFAULT_MESSAGES[403]) -> ApiError:
    return ApiError(403, detail, code="forbidden")


def not_found(detail: str = DEFAULT_MESSAGES[404]) -> ApiError:
    return ApiError(404, detail, code="not_found")


def conflict(detail: str = DEFAULT_MESSAGES[409]) -> ApiError:
    return ApiError(409, detail, code="conflict")


def validation_error(detail: str = DEFAULT_MESSAGES[422]) -> ApiError:
    return ApiError(422, detail, code="validation_error")


def error_body(detail: str, code: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"detail": detail, "code": code}
    body.update(extra)
    return body


# --- Validation error translation -----------------------------------------------------------------

_PYDANTIC_FR: dict[str, str] = {
    "missing": "champ requis",
    "string_too_short": "texte trop court",
    "string_too_long": "texte trop long",
    "string_type": "texte attendu",
    "int_type": "entier attendu",
    "int_parsing": "entier attendu",
    "float_type": "nombre attendu",
    "float_parsing": "nombre attendu",
    "bool_type": "booléen attendu",
    "bool_parsing": "booléen attendu",
    "uuid_type": "identifiant (UUID) attendu",
    "uuid_parsing": "identifiant (UUID) invalide",
    "enum": "valeur non autorisée",
    "literal_error": "valeur non autorisée",
    "greater_than_equal": "valeur trop petite",
    "greater_than": "valeur trop petite",
    "less_than_equal": "valeur trop grande",
    "less_than": "valeur trop grande",
    "too_short": "liste trop courte",
    "too_long": "liste trop longue",
    "value_error": "valeur invalide",
    "datetime_parsing": "date invalide (ISO 8601 attendu)",
    "datetime_type": "date attendue",
    "json_invalid": "JSON invalide",
    "dict_type": "objet attendu",
    "list_type": "liste attendue",
    "extra_forbidden": "champ non autorisé",
    "model_attributes_type": "objet attendu",
}


def _format_loc(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts) or "requête"


def _translate(err: dict[str, Any]) -> str:
    kind = str(err.get("type", ""))
    base = _PYDANTIC_FR.get(kind)
    ctx = err.get("ctx") or {}
    if kind == "value_error" and ctx.get("error"):
        return str(ctx["error"])
    if base is None:
        return str(err.get("msg", "valeur invalide"))
    if kind in {"greater_than_equal", "greater_than"} and "ge" in ctx:
        return f"{base} (minimum {ctx['ge']})"
    if kind in {"less_than_equal", "less_than"} and "le" in ctx:
        return f"{base} (maximum {ctx['le']})"
    if kind == "enum" and "expected" in ctx:
        return f"{base} (attendu : {ctx['expected']})"
    return base


def format_validation_errors(errors: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    items = [{"field": _format_loc(e.get("loc", ())), "message": _translate(e)} for e in errors]
    if not items:
        return DEFAULT_MESSAGES[422], items
    head = "; ".join(f"{i['field']} : {i['message']}" for i in items[:3])
    if len(items) > 3:
        head += f" (+{len(items) - 3})"
    return f"Données invalides — {head}", items


# --- Handlers -------------------------------------------------------------------------------------


def _response(status_code: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    request_id = get_request_id()
    merged = dict(headers or {})
    if request_id:
        merged["X-Request-ID"] = request_id
    return JSONResponse(status_code=status_code, content=body, headers=merged or None)


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status_code = exc.status_code
    code = getattr(exc, "code", None) or STATUS_CODES.get(status_code, "error")
    detail: Any = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code", code))
        detail = detail.get("detail", DEFAULT_MESSAGES.get(status_code, "Erreur"))
    if not isinstance(detail, str) or not detail or detail in _STARLETTE_DEFAULTS:
        detail = DEFAULT_MESSAGES.get(status_code, str(detail))
    return _response(status_code, error_body(detail, code), getattr(exc, "headers", None))


_STARLETTE_DEFAULTS = {
    "Not Found",
    "Method Not Allowed",
    "Unauthorized",
    "Forbidden",
    "Bad Request",
    "Internal Server Error",
    "Not Implemented",
    "Unprocessable Entity",
    "Conflict",
}


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    detail, items = format_validation_errors(list(exc.errors()))
    return _response(422, error_body(detail, "validation_error", errors=items))


async def _not_implemented_handler(request: Request, exc: NotImplementedError) -> JSONResponse:
    message = str(exc) or "Fonctionnalité non encore disponible sur cette instance"
    return _response(501, error_body(message, "not_implemented"))


async def _integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    logger.warning("Integrity error on %s %s: %s", request.method, request.url.path, exc.orig)
    return _response(409, error_body("Conflit avec une ressource existante", "conflict"))


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _response(500, error_body(DEFAULT_MESSAGES[500], "internal_error"))


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(NotImplementedError, _not_implemented_handler)  # type: ignore[arg-type]
    app.add_exception_handler(IntegrityError, _integrity_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)
