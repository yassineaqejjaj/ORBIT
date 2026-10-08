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
    #: Candidates scored by the cross-encoder and passage length sent (latency bound, §B2).
    reranker_top_n: int = Field(default=20, ge=1, le=200)
    reranker_max_chars: int = Field(default=800, ge=100, le=8000)

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

    # --- Sources (docs/AI_CONTEXT_ENGINEERING.md §F) ---------------------------------------------
    #: Meeting import (§F1): transcripts (VTT/SRT/DOCX/text) and optional audio transcription.
    meetings_enabled: bool = True
    #: OpenAI-compatible ``/audio/transcriptions`` endpoint (Whisper, faster-whisper…); empty = off.
    transcription_base_url: str = ""
    transcription_api_key: str = ""
    transcription_model: str = "whisper-1"
    transcription_timeout_seconds: float = 300.0
    #: Maximum audio file size sent for transcription (MB).
    transcription_max_mb: int = Field(default=25, ge=1, le=500)
    #: True when the transcription server is self-hosted: C2/C3 audio may then be transcribed. Otherwise the
    #: LLM guardrail ceiling (``ORBIT_LLM_MAX_CLASSIFICATION``) applies — C2/C3 audio never leaves ORBIT.
    transcription_local: bool = False
    #: Project e-mails (§F3): maximum messages read per mailbox folder / label and per synchronisation.
    mail_max_messages: int = Field(default=200, ge=1, le=5000)

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
    #: deterministic expansion from synonyms and project entities), ``deterministic`` (default: no
    #: LLM call — nor its latency — on the context hot path) or ``off``.
    query_rewrite: Literal["auto", "deterministic", "off"] = "deterministic"
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

    # --- Context assembly (docs/AI_CONTEXT_ENGINEERING.md §C) ------------------------------------
    #: §C1 prompt-cache-aware layout: stable prefix (notice, decisions, constraints, snapshot items)
    #: first, variable items and the task after it; ``cache_prefix_hash`` exposed in the package.
    context_cache_ordering: bool = True
    #: Window in which a previous request with the same prefix hash counts as a cache reuse.
    context_cache_ttl_seconds: int = Field(default=300, ge=1, le=86_400)
    #: §C2 ``progressive`` mode: tokens of each item's teaser in the summary index.
    context_progressive_excerpt_tokens: int = Field(default=40, ge=8, le=400)
    #: §C3 per-agent-kind context profiles (budget, sections, order, thresholds) applied to agents.
    context_profiles: bool = True
    #: §C4 sentence-level compression: ``learned`` (embedding relevance + redundancy + optional local
    #: pruning model) or ``extractive`` (term overlap + position).
    compression_mode: Literal["learned", "extractive"] = "learned"
    #: Optional local pruning model hook ``package.module:function`` (sentences, query) -> scores in [0, 1].
    compression_pruner: str = ""
    #: §C5 context sufficiency: score thresholds of the ``sufficient`` / ``partial`` verdicts.
    context_sufficiency: bool = True
    sufficiency_sufficient_threshold: float = Field(default=0.75, ge=0, le=1)
    sufficiency_partial_threshold: float = Field(default=0.4, ge=0, le=1)
    #: « Demander à ORBIT » answers « je ne sais pas » when the context is insufficient.
    ask_abstain_when_insufficient: bool = True

    # --- Memory (docs/AI_CONTEXT_ENGINEERING.md §D) ----------------------------------------------
    #: §D1 procedures served as skills and injected in the « Façons de faire » section.
    memory_skills: bool = True
    #: Max procedures anchored in a context when their task types / agent kinds match the request.
    skills_context_max: int = Field(default=3, ge=0, le=20)
    #: §D2 entity aliases used to expand retrieval queries.
    memory_entity_aliases: bool = True
    #: §D3 contradiction detection: ``auto`` (NLI hook if configured, else LLM judge if the guardrail
    #: allows, else lexical markers), ``nli``, ``llm`` or ``lexical`` (lexical markers always the fallback).
    memory_contradiction_mode: Literal["auto", "nli", "llm", "lexical"] = "auto"
    #: Optional local NLI hook ``package.module:function`` (premise, hypothesis) -> P(contradiction).
    memory_nli_model: str = ""
    #: Model contradiction probability above which a conflict is flagged.
    memory_contradiction_threshold: float = Field(default=0.7, ge=0, le=1)
    #: §D4 monthly reflection « ce qui a changé » (proposed long-term summary, human validation).
    memory_reflection: bool = True

    # --- Evaluation & interoperability (docs/AI_CONTEXT_ENGINEERING.md §E) -------------------------
    #: §E1 evaluation bench: default k of recall@k / nDCG@k and blocking recall threshold (CI, UI badge).
    eval_k: int = Field(default=5, ge=1, le=50)
    eval_min_recall: float = Field(default=0.6, ge=0, le=1)
    #: §E2 bounded learning of the ranking weights from feedback (max absolute change per weight).
    ranking_learning: bool = True
    ranking_learning_max_delta: float = Field(default=0.1, ge=0, le=0.3)
    ranking_learning_rate: float = Field(default=0.2, ge=0, le=1)
    ranking_learning_min_signals: int = Field(default=5, ge=1)
    #: §E3 LLM judge on a sample of served contexts (guardrail applies; never C2/C3 to an external LLM).
    judge_sample_rate: float = Field(default=0.0, ge=0, le=1)
    judge_alert_threshold: float = Field(default=0.5, ge=0, le=1)
    judge_window_days: int = Field(default=7, ge=1, le=90)
    judge_min_samples: int = Field(default=3, ge=1)
    #: §E5 A2A: Agent Card + signed snapshot handoff (HMAC-SHA256 JWS; secret defaults to the JWT secret).
    a2a_enabled: bool = True
    a2a_signing_secret: str = ""
    a2a_handoff_ttl_seconds: int = Field(default=600, ge=30, le=86400)
    #: §E6 OpenTelemetry GenAI semantic conventions: record prompt/completion contents on spans (off).
    otel_genai_capture_content: bool = False

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
