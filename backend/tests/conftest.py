"""Test fixtures.

Integration tests run against the docker compose infrastructure (``make infra``):

* Postgres on ``localhost:5433`` — a dedicated database ``orbit_test`` is (re)created and migrated
  with Alembic once per session;
* OpenSearch on ``localhost:9201`` with index prefix ``orbit-test`` (indices deleted at the end);
* Valkey on ``localhost:6380`` database 15.

Override with ``ORBIT_TEST_PG_URL`` (server URL without database) / ``ORBIT_TEST_DATABASE``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PG_SERVER_URL = os.environ.get("ORBIT_TEST_PG_URL", "postgresql://orbit:orbit@localhost:5433")
TEST_DATABASE = os.environ.get("ORBIT_TEST_DATABASE", "orbit_test")
OBJECTS_DIR = tempfile.mkdtemp(prefix="orbit-test-objects-")

ADMIN_EMAIL = "admin@orbit.local"
ADMIN_PASSWORD = "orbit-admin"
DEFAULT_PASSWORD = "Mot-de-passe-123"

# Must be set before any ``app`` import (settings are read at import time).
os.environ.update(
    {
        "ORBIT_ENV": "test",
        "ORBIT_DATABASE_URL": f"{PG_SERVER_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)}/{TEST_DATABASE}",
        "ORBIT_OPENSEARCH_URL": os.environ.get("ORBIT_TEST_OPENSEARCH_URL", "http://localhost:9201"),
        "ORBIT_VALKEY_URL": os.environ.get("ORBIT_TEST_VALKEY_URL", "redis://localhost:6380/15"),
        "ORBIT_INDEX_PREFIX": os.environ.get("ORBIT_TEST_INDEX_PREFIX", "orbit-test"),
        "ORBIT_EMBEDDING_PROVIDER": "hash",
        "ORBIT_RERANKER": "heuristic",
        "ORBIT_OBJECT_STORE_PATH": OBJECTS_DIR,
        "ORBIT_JWT_SECRET": "orbit-test-secret-0123456789abcdef0123456789",
        "ORBIT_OTLP_ENDPOINT": "",
        "ORBIT_LLM_BASE_URL": "",
        "ORBIT_LLM_MODEL": "",
        "ORBIT_BOOTSTRAP_ADMIN_EMAIL": ADMIN_EMAIL,
        "ORBIT_BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "ORBIT_WORKER_METRICS_PORT": "0",
        "ORBIT_METRICS_PORT": "0",
        # The ASGI test transport speaks plain http: Secure cookies would never be sent back.
        "ORBIT_COOKIE_SECURE": "false",
        # Every test shares one client IP and the bootstrap admin: throttling is exercised by dedicated
        # tests that lower these limits (tests/test_rate_limiting.py).
        "ORBIT_RATE_LIMIT_LOGIN": "100000/minute",
        "ORBIT_RATE_LIMIT_API": "100000/minute",
        "ORBIT_RATE_LIMIT_AGENT": "100000/minute",
        "ORBIT_LOGIN_LOCKOUT_THRESHOLD": "100",
        "ORBIT_LOG_LEVEL": "WARNING",
    }
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import APIRouter, FastAPI  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.deps import AgentEditorAccess, AgentViewerAccess, OwnerAccess, ProjectAccess  # noqa: E402
from app.governance.acl import effective_principals  # noqa: E402

# --- Database lifecycle -------------------------------------------------------------------------------


async def _recreate_database() -> None:
    try:
        conn = await asyncpg.connect(f"{PG_SERVER_URL}/postgres", timeout=10)
    except (OSError, asyncpg.PostgresError) as exc:
        raise RuntimeError(
            f"Postgres de test injoignable ({PG_SERVER_URL}). Lancez `make infra` (docker compose) : {exc}"
        ) from exc
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    finally:
        await conn.close()


def _delete_test_indices() -> None:
    url = os.environ["ORBIT_OPENSEARCH_URL"]
    with contextlib.suppress(httpx.HTTPError):
        prefix = os.environ["ORBIT_INDEX_PREFIX"]
        # Explicit names (no wildcard) so parallel test runs with other prefixes are untouched.
        httpx.delete(f"{url}/{prefix}-chunks-v1,{prefix}-memory-v1?ignore_unavailable=true", timeout=10)


@pytest.fixture(scope="session")
def database() -> str:
    """Create and migrate the ``orbit_test`` database (once per session)."""
    asyncio.run(_recreate_database())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
    )
    _delete_test_indices()
    yield os.environ["ORBIT_DATABASE_URL"]
    _delete_test_indices()


# --- Application ------------------------------------------------------------------------------------------


def _test_router() -> APIRouter:
    """Routes used only by the tests to exercise shared dependencies and error handlers."""
    router = APIRouter(prefix="/api/v1/_test")

    def _describe(access: ProjectAccess) -> dict[str, object]:
        principal = access.principal
        return {
            "kind": principal.kind,
            "role": access.role.value,
            "label": principal.label,
            "clearance": principal.clearance,
            "principals": sorted(effective_principals(access)),
        }

    @router.get("/projects/{slug}/viewer")
    async def viewer(access: AgentViewerAccess) -> dict[str, object]:
        return _describe(access)

    @router.post("/projects/{slug}/editor")
    async def editor(access: AgentEditorAccess) -> dict[str, object]:
        return _describe(access)

    @router.post("/projects/{slug}/owner")
    async def owner(access: OwnerAccess) -> dict[str, object]:
        return _describe(access)

    @router.get("/not-implemented")
    async def not_implemented() -> None:
        raise NotImplementedError

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("unexpected failure")

    return router


@pytest_asyncio.fixture(scope="session")
async def app(database: str) -> AsyncIterator[FastAPI]:
    from app.main import create_app

    application = create_app()
    application.include_router(_test_router())
    # The lifespan (MCP session manager task group) must be entered and exited in the same task:
    # pytest-asyncio runs fixture setup and teardown in different tasks, so host it in its own task.
    started, stop = asyncio.Event(), asyncio.Event()

    async def _host() -> None:
        async with application.router.lifespan_context(application):
            started.set()
            await stop.wait()

    host = asyncio.create_task(_host())
    waiter = asyncio.create_task(started.wait())
    await asyncio.wait({host, waiter}, return_when=asyncio.FIRST_COMPLETED)
    if host.done():
        waiter.cancel()
        host.result()  # re-raise the startup failure
    try:
        yield application
    finally:
        stop.set()
        await host


def _client(app: FastAPI, **kwargs: object) -> httpx.AsyncClient:
    """Test client behaving like the web UI: echoes the ``orbit_csrf`` cookie in ``X-CSRF-Token``."""
    transport = httpx.ASGITransport(app=app, **kwargs)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async def _csrf_header(request: httpx.Request) -> None:
        token = client.cookies.get("orbit_csrf")
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and token
            and "x-csrf-token" not in request.headers
        ):
            request.headers["X-CSRF-Token"] = token

    client.event_hooks["request"].append(_csrf_header)
    return client


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app) as c:
        yield c


@pytest_asyncio.fixture
async def lenient_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Client that turns unhandled server errors into 500 responses instead of raising."""
    async with _client(app, raise_app_exceptions=False) as c:
        yield c


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


@pytest_asyncio.fixture
async def admin_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app) as c:
        await login(c, ADMIN_EMAIL, ADMIN_PASSWORD)
        yield c


@pytest_asyncio.fixture
async def db_session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    from app.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        yield session


# --- Factories -------------------------------------------------------------------------------------------------


@dataclass
class UserInfo:
    id: uuid.UUID
    email: str
    password: str
    full_name: str


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def make_user(app: FastAPI) -> Callable[..., Awaitable[UserInfo]]:
    from app.db import get_sessionmaker
    from app.services.users import create_user

    async def _make(*, clearance: int = 1, is_admin: bool = False, name: str | None = None) -> UserInfo:
        email = f"{unique('user')}@example.com"
        full_name = name or f"Utilisateur {email.split('@')[0]}"
        async with get_sessionmaker()() as session:
            user = await create_user(
                session,
                email=email,
                full_name=full_name,
                password=DEFAULT_PASSWORD,
                clearance=clearance,
                is_admin=is_admin,
            )
            await session.commit()
            return UserInfo(id=user.id, email=email, password=DEFAULT_PASSWORD, full_name=full_name)

    return _make


@pytest_asyncio.fixture
async def client_for(app: FastAPI) -> AsyncIterator[Callable[[UserInfo], Awaitable[httpx.AsyncClient]]]:
    """Factory of logged-in clients (closed at teardown)."""
    opened: list[httpx.AsyncClient] = []

    async def _for(user: UserInfo) -> httpx.AsyncClient:
        c = _client(app)
        opened.append(c)
        await login(c, user.email, user.password)
        return c

    yield _for
    for c in opened:
        await c.aclose()


@pytest_asyncio.fixture
async def agent_client(app: FastAPI) -> AsyncIterator[Callable[[str], httpx.AsyncClient]]:
    """Factory of clients authenticated with an agent API key (``Authorization: Bearer orb_…``)."""
    opened: list[httpx.AsyncClient] = []

    def _for(api_key: str, *, header: str = "authorization") -> httpx.AsyncClient:
        c = _client(app)
        if header == "authorization":
            c.headers["Authorization"] = f"Bearer {api_key}"
        else:
            c.headers["X-Orbit-Key"] = api_key
        opened.append(c)
        return c

    yield _for
    for c in opened:
        await c.aclose()


@pytest_asyncio.fixture
async def project(admin_client: httpx.AsyncClient) -> dict[str, object]:
    """A fresh project owned by the bootstrap admin."""
    response = await admin_client.post(
        "/api/v1/projects", json={"name": f"Projet {unique('test')}", "description": "Projet de test"}
    )
    assert response.status_code == 201, response.text
    return response.json()
