"""Application settings (environment variables prefixed with ``ORBIT_``).

Every variable of docs/ARCHITECTURE.md §1 and docs/PRODUCTION.md §1 is declared here with its
documented default. ``ORBIT_ENV`` defaults to ``production``: the configuration is then validated
*fail-closed* (docs/PRODUCTION.md §2) and the process refuses to start with unsafe values.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.0"

#: Development-only secret, used when ``ORBIT_JWT_SECRET`` is empty outside production.
DEV_JWT_SECRET = "orbit-dev-secret-change-me-0123456789abcdef"
#: Historical bootstrap password: always refused in production.
LEGACY_BOOTSTRAP_PASSWORD = "orbit-admin"
#: Passwords considered "default" for datastores (refused in production).
DEFAULT_DATASTORE_PASSWORDS = frozenset(
    {"", "orbit", "postgres", "password", "admin", "changeme", "opensearch", "valkey", "redis", "secret"}
)

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SECRET_FIELDS = frozenset(
    {
        "jwt_secret",
        "jwt_previous_secrets",
        "bootstrap_admin_password",
        "oidc_client_secret",
        "metrics_token",
        "opensearch_password",
        "s3_access_key",
        "s3_secret_key",
        "encryption_key",
        "encryption_previous_keys",
        "embedding_api_key",
        "llm_api_key",
        "otlp_headers",
    }
)
_URL_FIELDS = frozenset({"database_url", "valkey_url", "opensearch_url"})

logger = logging.getLogger("orbit.config")

Env = Literal["development", "production", "test"]
MfaPolicy = Literal["none", "privileged", "all"]


class ConfigurationError(RuntimeError):
    """Unsafe configuration refused at startup (fail-closed).

    Deliberately not a ``ValueError``: pydantic would wrap it in a ``ValidationError`` and bury the list
    of problems; the process must stop with this exact, readable message.
    """


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _url_password(url: str) -> str | None:
    """Password embedded in a connection URL (``None`` when the URL carries no credentials)."""
    parts = urlsplit(url)
    if parts.password is None:
        return None
    return unquote(parts.password)


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.password is None:
        return url
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
    return parts._replace(netloc=netloc).geturl()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORBIT_",
        env_file=(str(_BACKEND_DIR.parent / ".env"), str(_BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -------------------------------------------------------------------------------
    env: Env = "production"
    log_level: str = "INFO"
    app_version: str = APP_VERSION
    demo_mode: bool = False
    #: Local ``make demo`` only: downgrades the fail-closed checks to loud warnings (requires DEMO_MODE).
    allow_insecure_demo: bool = False
    public_url: str = "http://localhost:3000"
    api_workers: int = Field(default=2, ge=1, le=64)
    #: Swagger / OpenAPI. Defaults to ``False`` in production, ``True`` otherwise.
    docs_enabled: bool = False

    # --- Infrastructure (ARCHITECTURE §1) --------------------------------------------------------
    database_url: str = "postgresql+asyncpg://orbit:orbit@postgres:5432/orbit"
    database_sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = "prefer"
    database_ca_certs: str = ""
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_max_overflow: int = Field(default=10, ge=0, le=200)
    db_statement_timeout_ms: int = Field(default=30000, ge=0)
    opensearch_url: str = "http://opensearch:9200"
    opensearch_user: str = ""
    opensearch_password: str = ""
    opensearch_ca_certs: str = ""
    opensearch_verify_certs: bool = True
    opensearch_shards: int = Field(default=1, ge=1, le=64)
    #: Replica count. Resolves to 1 in production, 0 otherwise, when not set explicitly.
    opensearch_replicas: int = Field(default=1, ge=0, le=16)
    valkey_url: str = "redis://valkey:6379/0"

    # --- Identity, sessions, cookies (PRODUCTION §1) --------------------------------------------
    jwt_secret: str = ""
    #: CSV of previous secrets still accepted for verification (rotation).
    jwt_previous_secrets: str = ""
    session_idle_minutes: int = Field(default=30, ge=1, le=24 * 60)
    session_absolute_hours: int = Field(default=12, ge=1, le=24 * 30)
    cookie_secure: bool = True
    #: CSV of IPs/CIDRs whose ``X-Forwarded-For`` / ``X-Forwarded-Proto`` headers are trusted.
    trusted_proxies: str = "127.0.0.1"
    password_min_length: int = Field(default=12, ge=8, le=128)
    mfa_required: MfaPolicy = "privileged"
    invitation_ttl_hours: int = Field(default=72, ge=1, le=24 * 30)

    # --- OIDC (SSO) ------------------------------------------------------------------------------
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_label: str = "SSO entreprise"
    oidc_groups_claim: str = "groups"
    oidc_admin_groups: str = ""
    #: JSON object ``{"group": clearance}``.
    oidc_clearance_map: str = "{}"
    oidc_default_clearance: int = Field(default=1, ge=0, le=3)
    oidc_allow_local_login: bool = True
    oidc_auto_provision: bool = True
    oidc_http_timeout_seconds: float = 10.0

    # --- Rate limiting (sliding windows in Valkey) ------------------------------------------------
    rate_limit_login: str = "5/minute,20/hour"
    rate_limit_api: str = "600/minute"
    rate_limit_agent: str = "300/minute"
    #: Consecutive failures before an account lockout (the lock duration doubles each time).
    login_lockout_threshold: int = Field(default=5, ge=1, le=100)
    login_lockout_base_seconds: int = Field(default=60, ge=1)
    login_lockout_max_seconds: int = Field(default=3600, ge=1)

    # --- Observability ---------------------------------------------------------------------------
    otlp_endpoint: str = ""
    otlp_headers: str = ""  # "key1=value1,key2=value2" (e.g. Langfuse basic auth)
    service_name: str = "orbit-api"
    metrics_token: str = ""
    metrics_port: int = Field(default=9464, ge=0, le=65535)

    # --- Storage ---------------------------------------------------------------------------------
    object_store_backend: Literal["local", "s3"] = "local"
    object_store_path: str = "/data/objects"
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_prefix: str = ""
    max_upload_mb: int = Field(default=50, ge=1)
    max_upload_total_mb: int = Field(default=200, ge=1)

    # --- Application encryption (envelope AES-256-GCM) --------------------------------------------
    #: Base64-encoded 32-byte master key (required in production, or ENCRYPTION_KEY_FILE).
    encryption_key: str = ""
    encryption_key_file: str = ""
    #: CSV of previous base64 master keys (decryption only, rotation).
    encryption_previous_keys: str = ""

    # --- Retention (days) ------------------------------------------------------------------------
    retention_context_days: int = Field(default=180, ge=1)
    retention_feedback_days: int = Field(default=365, ge=1)
    retention_jobs_days: int = Field(default=30, ge=1)
    retention_audit_days: int = Field(default=1095, ge=1)
    retention_sessions_days: int = Field(default=30, ge=1)
    retention_tombstone_days: int = Field(default=3650, ge=1)

    # --- Retrieval models ------------------------------------------------------------------------
    embedding_provider: Literal["fastembed", "openai", "hash"] = "fastembed"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    #: Local cache for fastembed models (baked into the Docker image). Falls back to FASTEMBED_CACHE_PATH.
    model_cache_dir: str = ""
    reranker: Literal["heuristic", "fastembed", "none"] = "heuristic"
    reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"
    external_embedding_max_classification: int = Field(default=1, ge=0, le=3)

    # --- Optional LLM (OpenAI-compatible) ---------------------------------------------------------
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: float = 30.0
    llm_max_classification: int = Field(default=1, ge=0, le=3)
    llm_redact_pii: bool = True

    # --- Indexing, cache & cost -------------------------------------------------------------------
    index_prefix: str = "orbit"
    cost_per_1k_tokens: float = 0.002
    semantic_cache_ttl_seconds: int = Field(default=300, ge=0)

    # --- Bootstrap -------------------------------------------------------------------------------
    bootstrap_admin_email: str = "admin@orbit.local"
    #: Empty => a random one-time password is generated and logged once (must be changed at login).
    bootstrap_admin_password: str = ""
    bootstrap_admin_name: str = "Administrateur ORBIT"

    # --- Worker ----------------------------------------------------------------------------------
    worker_concurrency: int = Field(default=2, ge=1, le=32)
    worker_poll_interval_seconds: float = 1.0
    worker_heartbeat_seconds: float = 30.0
    worker_job_timeout_seconds: float = 900.0
    worker_stale_lock_seconds: float = 1800.0
    worker_shutdown_grace_seconds: float = 30.0
    worker_maintenance_interval_seconds: float = 300.0
    worker_metrics_port: int = 9464  # 0 disables the worker Prometheus endpoint

    # --- Validators ------------------------------------------------------------------------------
    @model_validator(mode="before")
    @classmethod
    def _env_dependent_defaults(cls, data: Any) -> Any:
        """Defaults that depend on ``ENV`` (docs off / replicas 1 in production, on / 0 elsewhere)."""
        if not isinstance(data, dict):
            return data
        lowered = {str(key).lower(): key for key in data}
        env = str(data.get(lowered.get("env", "env"), "production")).lower()
        if "docs_enabled" not in lowered:
            data["docs_enabled"] = env != "production"
        if "opensearch_replicas" not in lowered:
            data["opensearch_replicas"] = 1 if env == "production" else 0
        return data

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("llm_base_url", "embedding_base_url", "otlp_endpoint", "public_url", "oidc_issuer")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("oidc_clearance_map")
    @classmethod
    def _valid_clearance_map(cls, value: str) -> str:
        raw = value.strip() or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ORBIT_OIDC_CLEARANCE_MAP doit être un objet JSON valide : {exc}") from exc
        if not isinstance(parsed, dict) or not all(
            isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 3
            for level in parsed.values()
        ):
            raise ValueError('ORBIT_OIDC_CLEARANCE_MAP doit être de la forme {"groupe": niveau 0..3}.')
        return raw

    @field_validator("rate_limit_login", "rate_limit_api", "rate_limit_agent")
    @classmethod
    def _valid_rate_limit(cls, value: str) -> str:
        from app.identity.ratelimit import parse_limits  # local import: avoids a cycle at module load

        parse_limits(value)
        return value

    @field_validator("trusted_proxies")
    @classmethod
    def _valid_proxies(cls, value: str) -> str:
        for item in _csv(value):
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError as exc:
                raise ValueError(f"ORBIT_TRUSTED_PROXIES : entrée invalide « {item} » ({exc}).") from exc
        return value

    @model_validator(mode="after")
    def _resolve_and_check(self) -> Settings:
        if not self.jwt_secret and self.env != "production":
            self.jwt_secret = DEV_JWT_SECRET
        if self.encryption_key:
            _decode_key(self.encryption_key, "ORBIT_ENCRYPTION_KEY")
        for previous in _csv(self.encryption_previous_keys):
            _decode_key(previous, "ORBIT_ENCRYPTION_PREVIOUS_KEYS")
        problems = self.production_problems()
        if problems:
            if self.allow_insecure_demo and self.demo_mode:
                for problem in problems:
                    logger.warning("CONFIGURATION NON SÛRE (ORBIT_ALLOW_INSECURE_DEMO) : %s", problem)
            else:
                raise ConfigurationError(
                    "Configuration refusée (ORBIT_ENV=production, fail-closed) :\n- " + "\n- ".join(problems)
                )
        if not self.jwt_secret:
            raise ConfigurationError("ORBIT_JWT_SECRET est requis (au moins 32 octets aléatoires).")
        return self

    def production_problems(self) -> list[str]:
        """Violations of the fail-closed rules of docs/PRODUCTION.md §2 (empty outside production)."""
        if self.env != "production":
            return []
        problems: list[str] = []
        if not self.jwt_secret or self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret.encode()) < 32:
            problems.append(
                "ORBIT_JWT_SECRET doit être défini (au moins 32 octets aléatoires, pas la valeur de dev)."
            )
        if not self.cookie_secure:
            problems.append("ORBIT_COOKIE_SECURE doit valoir true.")
        if self.bootstrap_admin_password and (
            self.bootstrap_admin_password == LEGACY_BOOTSTRAP_PASSWORD
            or len(self.bootstrap_admin_password) < 16
        ):
            problems.append(
                "ORBIT_BOOTSTRAP_ADMIN_PASSWORD refusé (valeur historique ou moins de 16 caractères) ; "
                "laissez-le vide pour générer un mot de passe à usage unique."
            )
        if not self.encryption_key and not self.encryption_key_file:
            problems.append("ORBIT_ENCRYPTION_KEY (ou ORBIT_ENCRYPTION_KEY_FILE) est requis.")
        elif (
            self.encryption_key_file
            and not self.encryption_key
            and not Path(self.encryption_key_file).is_file()
        ):
            problems.append(f"ORBIT_ENCRYPTION_KEY_FILE introuvable : {self.encryption_key_file}.")
        if not self.public_url.startswith("https://"):
            problems.append("ORBIT_PUBLIC_URL doit être en https://.")
        if self.demo_mode:
            problems.append(
                "ORBIT_DEMO_MODE=true est interdit en production (réservé à ORBIT_ENV=development)."
            )
        if self.docs_enabled:
            problems.append("ORBIT_DOCS_ENABLED=true est interdit en production.")
        if self.embedding_provider == "hash":
            problems.append("ORBIT_EMBEDDING_PROVIDER=hash (embeddings de test) est interdit en production.")
        if any(ipaddress.ip_network(item, strict=False).prefixlen == 0 for item in self.trusted_proxy_list):
            problems.append(
                "ORBIT_TRUSTED_PROXIES ne doit pas faire confiance à toutes les adresses (*, 0.0.0.0/0)."
            )
        db_password = _url_password(self.database_url)
        if db_password is None or db_password in DEFAULT_DATASTORE_PASSWORDS:
            problems.append("Mot de passe Postgres absent ou par défaut dans ORBIT_DATABASE_URL.")
        if self.opensearch_user and self.opensearch_password in DEFAULT_DATASTORE_PASSWORDS:
            problems.append("ORBIT_OPENSEARCH_PASSWORD absent ou par défaut.")
        if not self.opensearch_user and _url_password(self.opensearch_url) is None:
            problems.append(
                "OpenSearch sans authentification (ORBIT_OPENSEARCH_USER / ORBIT_OPENSEARCH_PASSWORD)."
            )
        valkey_password = _url_password(self.valkey_url)
        if valkey_password is None or valkey_password in DEFAULT_DATASTORE_PASSWORDS:
            problems.append(
                "Mot de passe Valkey absent ou par défaut dans ORBIT_VALKEY_URL (redis[s]://:mdp@hôte)."
            )
        if self.oidc_enabled and not (self.oidc_issuer and self.oidc_client_id):
            problems.append(
                "ORBIT_OIDC_ISSUER et ORBIT_OIDC_CLIENT_ID sont requis lorsque ORBIT_OIDC_ENABLED=true."
            )
        if self.oidc_enabled and not self.oidc_issuer.startswith("https://"):
            problems.append("ORBIT_OIDC_ISSUER doit être en https://.")
        return problems

    # --- Derived values ---------------------------------------------------------------------------
    @property
    def chunks_index(self) -> str:
        return f"{self.index_prefix}-chunks-v1"

    @property
    def memory_index(self) -> str:
        return f"{self.index_prefix}-memory-v1"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    @property
    def session_ttl_seconds(self) -> int:
        """Absolute lifetime of a user session (JWT ``exp`` and cookie ``Max-Age``)."""
        return self.session_absolute_hours * 3600

    @property
    def session_idle_seconds(self) -> int:
        return self.session_idle_minutes * 60

    @property
    def jwt_verification_secrets(self) -> list[str]:
        return [self.jwt_secret, *_csv(self.jwt_previous_secrets)]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return _csv(self.trusted_proxies)

    @property
    def oidc_admin_group_list(self) -> list[str]:
        return _csv(self.oidc_admin_groups)

    @property
    def oidc_clearance_mapping(self) -> dict[str, int]:
        parsed: dict[str, int] = json.loads(self.oidc_clearance_map or "{}")
        return parsed

    @property
    def local_login_enabled(self) -> bool:
        return not self.oidc_enabled or self.oidc_allow_local_login

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_upload_total_bytes(self) -> int:
        return self.max_upload_total_mb * 1024 * 1024

    @property
    def public_origin(self) -> str:
        parts = urlsplit(self.public_url)
        return f"{parts.scheme}://{parts.netloc}"

    def redacted_summary(self) -> dict[str, Any]:
        """Effective configuration with secrets masked (logged once at startup)."""
        summary: dict[str, Any] = {}
        for name in type(self).model_fields:
            value = getattr(self, name)
            if name in _SECRET_FIELDS:
                summary[name] = "***" if value else ""
            elif name in _URL_FIELDS and isinstance(value, str):
                summary[name] = _redact_url(value)
            else:
                summary[name] = value
        return summary


def _decode_key(value: str, variable: str) -> bytes:
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{variable} doit être encodée en base64 : {exc}") from exc
    if len(raw) != 32:
        raise ValueError(f"{variable} doit contenir exactement 32 octets (base64), reçu {len(raw)}.")
    return raw


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (cached). Tests may call ``get_settings.cache_clear()``."""
    return Settings()


settings = get_settings()
