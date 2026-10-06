"""ORBIT API application: REST ``/api/v1``, MCP ``/mcp``, ``/metrics``, ``/health``, ``/ready``."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api import API_PREFIX, api_router
from app.config import settings
from app.db import dispose_engine, get_engine, get_sessionmaker
from app.errors import install_exception_handlers
from app.observability.logging_setup import setup_logging
from app.observability.metrics import metrics_asgi_app
from app.observability.middleware import RequestContextMiddleware
from app.observability.tracing import instrument_fastapi, setup_tracing, shutdown_tracing
from app.schemas import DependencyCheck, Health, Ready
from app.services.users import ensure_bootstrap_admin

logger = logging.getLogger("orbit.main")

READY_TIMEOUT_SECONDS = 3.0

OPENAPI_TAGS = [
    {"name": "auth", "description": "Connexion, session"},
    {"name": "users", "description": "Administration des utilisateurs (admin)"},
    {"name": "projects", "description": "Projets et paramètres"},
    {"name": "members", "description": "Membres et rôles"},
    {"name": "agents", "description": "Agents IA et clés API"},
    {"name": "sources", "description": "Sources métier"},
    {"name": "documents", "description": "Documents, versions, oubli"},
    {"name": "jobs", "description": "File d'ingestion"},
    {"name": "search", "description": "Recherche hybride"},
    {"name": "memory", "description": "Mémoire gouvernée"},
    {"name": "sessions", "description": "Mémoire court terme"},
    {"name": "context", "description": "Assemblage de contexte"},
    {"name": "snapshots", "description": "Snapshots de contexte"},
    {"name": "metrics", "description": "Vue projet, métriques, export des traces"},
    {"name": "audit", "description": "Journal d'audit"},
    {"name": "compliance", "description": "Rapport de traçabilité IA (AI Act)"},
    {"name": "meta", "description": "Métadonnées de la plateforme"},
    {"name": "system", "description": "Santé et disponibilité"},
]


# --- Startup tasks --------------------------------------------------------------------------------


async def _bootstrap_admin() -> None:
    try:
        async with get_sessionmaker()() as session:
            await ensure_bootstrap_admin(session)
    except IntegrityError:
        logger.info("Bootstrap administrator already created by another process")
    except Exception:
        logger.exception("Bootstrap administrator creation failed (database not ready or not migrated?)")


async def _ensure_indices() -> None:
    from app.search import opensearch

    try:
        await opensearch.ensure_indices()
        logger.info("OpenSearch indices ready (%s, %s)", settings.chunks_index, settings.memory_index)
    except NotImplementedError:
        logger.warning("OpenSearch index setup not implemented yet — skipped")
    except Exception as exc:
        logger.warning("OpenSearch index setup failed (search degraded until it succeeds): %s", exc)


def _prepare_object_store() -> None:
    from app.storage.object_store import get_object_store

    try:
        get_object_store().ensure_root()
    except OSError as exc:
        logger.warning("Object store directory %s unavailable: %s", settings.object_store_path, exc)


async def _close_clients() -> None:
    from app.llm import client as llm_client
    from app.memory import short_term
    from app.search import opensearch

    for closer in (opensearch.close_client, short_term.close_valkey, llm_client.close):
        try:
            await closer()
        except Exception:  # pragma: no cover
            logger.debug("Client close failed", exc_info=True)


# --- Readiness ------------------------------------------------------------------------------------


async def _timed_check(check: Callable[[], Awaitable[dict[str, Any] | None]]) -> DependencyCheck:
    started = time.perf_counter()
    try:
        info = await asyncio.wait_for(check(), timeout=READY_TIMEOUT_SECONDS)
        return DependencyCheck(
            status="ok", latency_ms=round((time.perf_counter() - started) * 1000, 1), info=info
        )
    except NotImplementedError:
        return DependencyCheck(status="not_implemented")
    except TimeoutError:
        return DependencyCheck(status="error", detail="Délai dépassé")
    except Exception as exc:
        return DependencyCheck(status="error", detail=str(exc)[:300] or type(exc).__name__)


async def _check_postgres() -> dict[str, Any]:
    async with get_engine().connect() as conn:
        revision = None
        await conn.execute(text("SELECT 1"))
        try:
            revision = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        except Exception:
            revision = None
    return {"migration": revision}


async def _check_opensearch() -> dict[str, Any]:
    from app.search import opensearch

    return await opensearch.ping()


async def _check_valkey() -> dict[str, Any]:
    from app.memory.short_term import get_valkey

    await get_valkey().ping()
    return {}


async def _check_model() -> dict[str, Any]:
    from app.search.embeddings import get_embedder

    embedder = await asyncio.to_thread(get_embedder)
    return {"provider": settings.embedding_provider, "model": embedder.model_name, "dim": embedder.dim}


async def health() -> Health:
    return Health()


async def ready() -> JSONResponse:
    names = ("postgres", "opensearch", "valkey", "model")
    results = await asyncio.gather(
        _timed_check(_check_postgres),
        _timed_check(_check_opensearch),
        _timed_check(_check_valkey),
        _check_model_guarded(),
    )
    checks = dict(zip(names, results, strict=True))
    healthy = all(c.status in ("ok", "not_implemented", "disabled") for c in checks.values())
    body = Ready(status="ok" if healthy else "degraded", version=settings.app_version, checks=checks)
    return JSONResponse(status_code=200 if healthy else 503, content=body.model_dump(mode="json"))


async def _check_model_guarded() -> DependencyCheck:
    # Loading a local model can take a while on first call: allow more than the default timeout.
    started = time.perf_counter()
    try:
        info = await asyncio.wait_for(_check_model(), timeout=60)
        return DependencyCheck(
            status="ok", latency_ms=round((time.perf_counter() - started) * 1000, 1), info=info
        )
    except NotImplementedError:
        return DependencyCheck(status="not_implemented")
    except Exception as exc:
        return DependencyCheck(status="error", detail=str(exc)[:300] or type(exc).__name__)


# --- Application factory --------------------------------------------------------------------------


class _Asgi:
    """Wrap an ASGI callable so that Starlette's ``Route`` treats it as an app, not as a request handler."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


def _mcp_lifespan_target(mcp_app: ASGIApp | None) -> Starlette | None:
    return mcp_app if isinstance(mcp_app, Starlette) else None


def create_app() -> FastAPI:
    setup_logging(settings.log_level)
    setup_tracing(settings.service_name)

    from app.mcp_server import build_mcp_app

    try:
        mcp_app = build_mcp_app()
    except Exception:
        logger.exception("MCP server initialisation failed — /mcp disabled")
        mcp_app = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("ORBIT API %s starting (env=%s)", settings.app_version, settings.env)
        _prepare_object_store()
        await _bootstrap_admin()
        await _ensure_indices()
        async with AsyncExitStack() as stack:
            target = _mcp_lifespan_target(mcp_app)
            if target is not None:
                await stack.enter_async_context(target.router.lifespan_context(target))
                logger.info("MCP server mounted on /mcp")
            try:
                yield
            finally:
                logger.info("ORBIT API shutting down")
        await _close_clients()
        await dispose_engine()
        shutdown_tracing()

    app = FastAPI(
        title="ORBIT API",
        version=settings.app_version,
        description=(
            "Contexte et mémoire gouvernés pour agents IA — pertinence, fraîcheur, provenance, droits."
        ),
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=f"{API_PREFIX}/docs/oauth2-redirect",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    install_exception_handlers(app)
    app.include_router(api_router)
    app.add_api_route("/health", health, methods=["GET"], response_model=Health, tags=["system"])
    app.add_api_route(
        "/ready",
        ready,
        methods=["GET"],
        response_model=Ready,
        tags=["system"],
        responses={503: {"model": Ready, "description": "Dépendance indisponible"}},
    )
    app.router.routes.append(Route("/metrics", endpoint=_Asgi(metrics_asgi_app()), include_in_schema=False))
    if mcp_app is not None:
        # Forward /mcp and /mcp/ untouched to the MCP transport (built with streamable_http_path="/mcp").
        app.router.routes.append(Route("/mcp", endpoint=_Asgi(mcp_app), include_in_schema=False))
        app.router.routes.append(Route("/mcp/", endpoint=_Asgi(mcp_app), include_in_schema=False))
    # CORS is intentionally not enabled: the UI calls the API same-origin through the Next.js proxy.
    app.add_middleware(RequestContextMiddleware)
    instrument_fastapi(app)
    return app


app = create_app()
