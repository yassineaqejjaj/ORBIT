"""Fail-closed production configuration (docs/PRODUCTION.md §2), trusted proxies, docs/metrics exposure."""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.config import DEV_JWT_SECRET, ConfigurationError, Settings
from app.identity.netutil import resolve_client_ip

KEY = base64.b64encode(b"k" * 32).decode()

SAFE_PRODUCTION: dict[str, Any] = {
    "env": "production",
    "jwt_secret": "p" * 48,
    "cookie_secure": True,
    "encryption_key": KEY,
    "public_url": "https://orbit.example.com/",
    "database_url": "postgresql+asyncpg://orbit:S3cure-db-pass@db:5432/orbit",
    "opensearch_url": "https://opensearch:9200",
    "opensearch_user": "orbit",
    "opensearch_password": "S3cure-os-pass",
    "valkey_url": "rediss://:S3cure-valkey-pass@valkey:6379/0",
    "embedding_provider": "fastembed",
    "bootstrap_admin_password": "",
    "demo_mode": False,
    "allow_insecure_demo": False,
    "trusted_proxies": "10.0.0.0/8",
    "oidc_enabled": False,
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings built here must not inherit the test-suite environment (``ORBIT_*`` set by conftest)."""
    for name in list(os.environ):
        if name.startswith("ORBIT_"):
            monkeypatch.delenv(name)


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**SAFE_PRODUCTION, **overrides})  # type: ignore[call-arg]


@pytest.mark.usefixtures("clean_env")
def test_safe_production_configuration_is_accepted() -> None:
    config = _settings()
    assert config.production_problems() == []
    assert config.docs_enabled is False
    assert config.opensearch_replicas == 1
    assert config.public_url == "https://orbit.example.com"
    assert config.public_origin == "https://orbit.example.com"
    summary = config.redacted_summary()
    assert summary["jwt_secret"] == "***"
    assert "S3cure-db-pass" not in summary["database_url"]


@pytest.mark.usefixtures("clean_env")
def test_defaults_are_production_and_refused() -> None:
    with pytest.raises(ConfigurationError) as caught:
        Settings(_env_file=None)  # type: ignore[call-arg]
    message = str(caught.value)
    for fragment in ("ORBIT_JWT_SECRET", "ORBIT_ENCRYPTION_KEY", "ORBIT_PUBLIC_URL", "Postgres", "Valkey"):
        assert fragment in message


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"jwt_secret": DEV_JWT_SECRET}, "ORBIT_JWT_SECRET"),
        ({"jwt_secret": "court"}, "ORBIT_JWT_SECRET"),
        ({"cookie_secure": False}, "ORBIT_COOKIE_SECURE"),
        ({"bootstrap_admin_password": "orbit-admin"}, "ORBIT_BOOTSTRAP_ADMIN_PASSWORD"),
        ({"bootstrap_admin_password": "trop-court-15ca"}, "ORBIT_BOOTSTRAP_ADMIN_PASSWORD"),
        ({"encryption_key": ""}, "ORBIT_ENCRYPTION_KEY"),
        ({"public_url": "http://orbit.example.com"}, "ORBIT_PUBLIC_URL"),
        ({"demo_mode": True}, "ORBIT_DEMO_MODE"),
        ({"docs_enabled": True}, "ORBIT_DOCS_ENABLED"),
        ({"embedding_provider": "hash"}, "ORBIT_EMBEDDING_PROVIDER"),
        ({"trusted_proxies": "0.0.0.0/0"}, "ORBIT_TRUSTED_PROXIES"),
        ({"database_url": "postgresql+asyncpg://orbit:orbit@db/orbit"}, "Postgres"),
        ({"opensearch_user": "", "opensearch_url": "http://opensearch:9200"}, "OpenSearch"),
        ({"valkey_url": "redis://valkey:6379/0"}, "Valkey"),
        ({"oidc_enabled": True, "oidc_issuer": "http://idp", "oidc_client_id": "orbit"}, "ORBIT_OIDC_ISSUER"),
    ],
)
@pytest.mark.usefixtures("clean_env")
def test_unsafe_production_values_are_refused(overrides: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ConfigurationError, match=fragment):
        _settings(**overrides)


@pytest.mark.usefixtures("clean_env")
def test_long_bootstrap_password_is_accepted() -> None:
    assert _settings(bootstrap_admin_password="Un-Secret-Tres-Long-2026").production_problems() == []


@pytest.mark.usefixtures("clean_env")
def test_insecure_demo_downgrades_to_warnings(caplog: pytest.LogCaptureFixture) -> None:
    config = _settings(demo_mode=True, allow_insecure_demo=True, cookie_secure=False)
    assert any("ORBIT_DEMO_MODE" in problem for problem in config.production_problems())
    assert "CONFIGURATION NON SÛRE" in caplog.text
    with pytest.raises(ConfigurationError):
        _settings(allow_insecure_demo=True, cookie_secure=False)  # without DEMO_MODE: still refused


@pytest.mark.usefixtures("clean_env")
def test_development_and_test_envs_get_a_dev_secret_and_docs() -> None:
    config = Settings(_env_file=None, env="development")  # type: ignore[call-arg]
    assert config.jwt_secret == DEV_JWT_SECRET
    assert config.docs_enabled is True
    assert config.opensearch_replicas == 0
    assert config.production_problems() == []


@pytest.mark.usefixtures("clean_env")
def test_invalid_values_are_rejected_at_parse_time() -> None:
    with pytest.raises(ValidationError, match="TRUSTED_PROXIES"):
        Settings(_env_file=None, env="test", trusted_proxies="pas-une-ip")  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="Limite de débit invalide"):
        Settings(_env_file=None, env="test", rate_limit_login="vite")  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="ENCRYPTION_KEY"):
        Settings(_env_file=None, env="test", encryption_key="dGVzdA==")  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="CLEARANCE_MAP"):
        Settings(_env_file=None, env="test", oidc_clearance_map='{"g": 9}')  # type: ignore[call-arg]


# --- Trusted proxies ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("203.0.113.9", "1.2.3.4", "203.0.113.9"),  # untrusted peer: header ignored (spoofing)
        ("127.0.0.1", "198.51.100.7", "198.51.100.7"),
        ("127.0.0.1", "1.2.3.4, 198.51.100.7", "198.51.100.7"),  # right-most untrusted hop wins
        ("10.1.2.3", "198.51.100.7, 10.0.0.5", "198.51.100.7"),  # chain of trusted proxies
        ("127.0.0.1", "garbage", "127.0.0.1"),
        ("127.0.0.1", None, "127.0.0.1"),
        ("10.1.2.3", "[2001:db8::1]:443", "2001:db8::1"),
        ("10.1.2.3", "198.51.100.7:51234", "198.51.100.7"),
    ],
)
def test_client_ip_resolution(peer: str, forwarded: str | None, expected: str) -> None:
    assert resolve_client_ip(peer, forwarded, "127.0.0.1,10.0.0.0/8") == expected


async def test_audit_ip_ignores_spoofed_header_from_untrusted_peer(app: FastAPI) -> None:
    from sqlalchemy import select

    from app.db import get_sessionmaker
    from app.models import AuditLog

    transport = httpx.ASGITransport(app=app, client=("203.0.113.50", 4242))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        await c.post(
            "/api/v1/auth/login",
            json={"email": "spoof-check@example.com", "password": "x"},
            headers={"X-Forwarded-For": "1.1.1.1"},
        )
    async with get_sessionmaker()() as db:
        entry = await db.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "auth.login_failed", AuditLog.summary.contains("spoof-check@example.com")
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
    assert entry is not None
    assert entry.details["ip"] == "203.0.113.50"


# --- Exposure of docs, metrics, readiness ----------------------------------------------------------------


async def test_docs_disabled_hides_swagger_and_openapi(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.main import create_app

    monkeypatch.setattr(settings, "docs_enabled", False)
    hidden = create_app()
    transport = httpx.ASGITransport(app=hidden)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        for path in ("/api/v1/docs", "/api/v1/redoc", "/api/v1/openapi.json"):
            assert (await c.get(path)).status_code == 404, path


async def test_metrics_require_the_token_when_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "metrics_token", "jeton-de-supervision")
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer faux"})).status_code == 401
    ok = await client.get("/metrics", headers={"Authorization": "Bearer jeton-de-supervision"})
    assert ok.status_code == 200
    assert "orbit_context_requests_total" in ok.text


async def test_metrics_not_public_without_token(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "metrics_token", "")
    assert (await client.get("/metrics")).status_code == 404


async def test_ready_hides_details_in_production(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "metrics_token", "jeton-ready")
    public = (await client.get("/ready")).json()
    assert all(
        check.get("info") is None and check.get("detail") is None for check in public["checks"].values()
    )
    detailed = (await client.get("/ready", headers={"Authorization": "Bearer jeton-ready"})).json()
    assert detailed["checks"]["postgres"]["info"]["migration"]


async def test_incompatible_index_is_fatal_only_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main
    from app.config import settings
    from app.search import opensearch

    async def incompatible() -> None:
        raise opensearch.IndexConfigurationError("dimension des vecteurs 768 ≠ ORBIT_EMBEDDING_DIM=384")

    monkeypatch.setattr(opensearch, "ensure_indices", incompatible)
    await main._ensure_indices()  # ORBIT_ENV=test: degraded, the API still starts
    monkeypatch.setattr(settings, "env", "production")
    with pytest.raises(opensearch.IndexConfigurationError):
        await main._ensure_indices()
