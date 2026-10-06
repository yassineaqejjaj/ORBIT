"""Application settings (environment variables prefixed with ``ORBIT_``).

Every variable of docs/ARCHITECTURE.md §1 is declared here with its documented default.
A few operational variables (bootstrap admin, worker tuning, logging) complete the list;
they are all documented in ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.0"

#: Development-only secret. Refused when ``ORBIT_ENV=production``.
DEV_JWT_SECRET = "orbit-dev-secret-change-me-0123456789abcdef"

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORBIT_",
        env_file=(str(_BACKEND_DIR.parent / ".env"), str(_BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -------------------------------------------------------------------------------
    env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    app_version: str = APP_VERSION

    # --- Infrastructure (ARCHITECTURE §1) --------------------------------------------------------
    database_url: str = "postgresql+asyncpg://orbit:orbit@postgres:5432/orbit"
    database_pool_size: int = 10
    database_max_overflow: int = 10
    opensearch_url: str = "http://opensearch:9200"
    valkey_url: str = "redis://valkey:6379/0"

    # --- Security --------------------------------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_minutes: int = Field(default=720, ge=5, le=60 * 24 * 30)
    cookie_secure: bool = False

    # --- Storage ---------------------------------------------------------------------------------
    object_store_path: str = "/data/objects"
    max_upload_mb: int = 50

    # --- Retrieval models ------------------------------------------------------------------------
    embedding_provider: Literal["fastembed", "openai", "hash"] = "fastembed"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    #: Local cache for fastembed models (baked into the Docker image). Falls back to FASTEMBED_CACHE_PATH.
    model_cache_dir: str = ""
    reranker: Literal["heuristic", "fastembed", "none"] = "heuristic"
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

    # --- Optional LLM (OpenAI-compatible) ---------------------------------------------------------
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: float = 30.0
    #: "openai" = OpenAI-compatible chat completions (vLLM, Ollama, LiteLLM); "anthropic" = Messages API.
    llm_provider: Literal["openai", "anthropic"] = "openai"
    #: Guardrail (docs/FEATURES.md): highest classification sent to an EXTERNAL LLM (0-3).
    llm_max_classification: int = Field(default=1, ge=0, le=3)
    #: True when the LLM is self-hosted: lifts the classification ceiling.
    llm_local: bool = False
    llm_redact_pii: bool = True

    # --- Product features (docs/FEATURES.md) ----------------------------------------------------
    #: Fernet key (urlsafe base64, 32 bytes) encrypting connector / integration secrets.
    encryption_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    webhook_timeout_seconds: float = 10.0
    webhook_max_failures: int = 20
    connector_default_schedule_minutes: int = 60
    # --- MCP connectors (docs/FEATURES.md F6) ---
    #: Allow custom MCP servers (arbitrary command or URL) — platform admins only.
    mcp_allow_custom: bool = False
    #: Timeout of one MCP call (start-up, tool call), seconds; the server process is killed on timeout.
    mcp_timeout_seconds: float = 60.0
    #: Maximum items ingested per synchronisation of an MCP connector.
    mcp_max_items: int = 500
    #: Maximum size of one item's content (bytes); larger items are skipped.
    mcp_max_content_bytes: int = 5_000_000
    #: Overall duration budget of one MCP synchronisation, seconds.
    mcp_sync_timeout_seconds: float = 1800.0
    #: MarkItDown MCP fallback extractor (pptx, xlsx, msg, epub…): ``auto`` (if installed) or ``off``.
    markitdown_mcp: Literal["auto", "off"] = "auto"
    #: Command of the MarkItDown MCP server (stdio).
    markitdown_mcp_command: str = "markitdown-mcp"

    # --- AI security (docs/AI_CONTEXT_ENGINEERING.md §A) -----------------------------------------
    #: Prompt-injection detector at ingestion (score + reasons per chunk, quarantine above the threshold).
    injection_detection: bool = True
    injection_threshold: float = Field(default=0.6, gt=0.0, le=1.0)
    #: Optional local classifier on top of the rules (``local``); never an external call.
    injection_classifier: Literal["off", "local"] = "off"
    #: Spotlighting: served content wrapped in untrusted-data delimiters + header instruction.
    spotlighting: bool = True
    #: Ranking penalty of low-trust sources (medium = half of it); 0 disables trust in ranking.
    trust_ranking_penalty: float = Field(default=0.15, ge=0.0, le=1.0)
    #: Poisoning alert: at least N memory proposals/facts from one source or agent within the window.
    poisoning_alert_threshold: int = Field(default=8, ge=1)
    poisoning_window_hours: int = Field(default=24, ge=1)

    # --- Retrieval (docs/AI_CONTEXT_ENGINEERING.md §B) -------------------------------------------
    #: Contextual-retrieval preamble per chunk: ``auto`` (LLM when the guardrail allows, else
    #: deterministic), ``deterministic`` (never an LLM) or ``off``.
    contextual_retrieval: Literal["auto", "deterministic", "off"] = "auto"
    #: Maximum chunks of one document contextualised by the LLM (the rest is deterministic).
    contextual_llm_max_chunks: int = Field(default=64, ge=0, le=2000)
    #: Chunks processed per progressive re-index job (existing projects without preamble).
    contextual_reindex_batch: int = Field(default=200, ge=10, le=5000)
    #: Query rewriting: ``auto`` (multi-query, decomposition, HyDE with the LLM when allowed, else
    #: deterministic expansion from synonyms and project entities), ``deterministic`` or ``off``.
    query_rewrite: Literal["auto", "deterministic", "off"] = "auto"
    #: HyDE (hypothetical answer embedded as an extra query) when the LLM is used for rewriting.
    query_rewrite_hyde: bool = True
    #: Maximum extra queries per context request (rewrites, sub-questions, expansions).
    query_rewrite_max_queries: int = Field(default=4, ge=0, le=8)
    #: Iterative retrieval: rounds (1 = single pass; ≤ 3) re-searching uncovered sub-topics.
    retrieval_max_rounds: int = Field(default=3, ge=1, le=3)
    #: Visual documents: images of PDF/PPTX described and indexed (``auto``: vision LLM when the
    #: guardrail allows, else OCR when installed, else alternative text) or ``off``.
    visual_extraction: Literal["auto", "off"] = "auto"
    #: Vision LLM for image descriptions (requires a multimodal ``ORBIT_LLM_MODEL``).
    visual_llm: bool = True
    visual_max_images: int = Field(default=20, ge=0, le=200)
    #: Images smaller than this (pixels on the shorter side) are ignored (logos, icons, bullets).
    visual_min_size: int = Field(default=96, ge=1)

    # --- Observability ---------------------------------------------------------------------------
    otlp_endpoint: str = ""
    otlp_headers: str = ""  # "key1=value1,key2=value2" (e.g. Langfuse basic auth)
    service_name: str = "orbit-api"

    # --- Indexing & cost -------------------------------------------------------------------------
    index_prefix: str = "orbit"
    cost_per_1k_tokens: float = 0.002

    # --- Bootstrap -------------------------------------------------------------------------------
    bootstrap_admin_email: str = "admin@orbit.local"
    bootstrap_admin_password: str = "orbit-admin"
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

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("llm_base_url", "embedding_base_url", "otlp_endpoint")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Settings:
        if self.env == "production" and (self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32):
            raise ValueError(
                "ORBIT_JWT_SECRET doit être défini (au moins 32 caractères) lorsque ORBIT_ENV=production."
            )
        return self

    # --- Derived values ---------------------------------------------------------------------------
    @property
    def chunks_index(self) -> str:
        return f"{self.index_prefix}-chunks-v1"

    @property
    def memory_index(self) -> str:
        return f"{self.index_prefix}-memory-v1"

    @property
    def llm_enabled(self) -> bool:
        if self.llm_provider == "anthropic":
            # Base URL and model have defaults for the Messages API; only the key is required.
            return bool(self.llm_api_key)
        return bool(self.llm_base_url and self.llm_model)

    @property
    def session_ttl_seconds(self) -> int:
        return self.jwt_ttl_minutes * 60

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (cached). Tests may call ``get_settings.cache_clear()``."""
    return Settings()


settings = get_settings()
