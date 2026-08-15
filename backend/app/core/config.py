"""Application settings — everything env-driven via pydantic-settings.

All variables are prefixed ``QONVO_`` in the environment (see ``.env.example``).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QONVO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    environment: str = "development"
    debug: bool = False
    domain: str = "qonvo.local"
    log_level: str = "INFO"

    # --- Datastores ---
    database_url: str = Field(
        default="postgresql+asyncpg://qonvo_app:qonvo@postgres:5432/qonvo",
        description=(
            "Async SQLAlchemy DSN (asyncpg driver) for the APP role. Must be a "
            "non-superuser role — Postgres superusers bypass RLS entirely."
        ),
    )
    migrations_database_url: str | None = Field(
        default=None,
        description=(
            "DSN for the schema OWNER role, used only by Alembic. "
            "Falls back to database_url if unset."
        ),
    )
    system_database_url: str | None = Field(
        default=None,
        description=(
            "DSN for the BYPASSRLS system role (webhook tenant resolution, "
            "scheduler). Falls back to database_url if unset (dev only)."
        ),
    )
    redis_url: str = "redis://redis:6379/0"

    # --- WAHA ---
    waha_base_url: str = "http://waha:3000"
    waha_api_key: str = "change-me"
    # HMAC secret used to verify inbound webhook signatures (X-Webhook-Hmac).
    waha_hmac_secret: str = "change-me"
    waha_default_engine: str = "WEBJS"
    # URL WAHA posts webhooks to (reachable from the waha container → api service).
    webhook_url: str = "http://api:8000/webhooks/waha"
    webhook_retries: int = 3

    # --- Security ---
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_audience: str | None = None
    jwt_issuer: str | None = None
    # Fernet key for encrypting per-tenant integration credentials at rest.
    fernet_key: str = "change-me"

    # --- MinIO / object storage ---
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "qonvo"
    minio_secret_key: str = "change-me"
    minio_bucket: str = "qonvo-media"
    minio_secure: bool = False

    # --- Pipeline tuning (DESIGN.md §5) ---
    debounce_window_seconds: float = 5.0
    dedupe_ttl_seconds: int = 86_400
    # Per-(session, chat) inbound cap — drops messages beyond this many in the
    # window, bounding LLM spend from a single customer flooding the number.
    inbound_rate_limit: int = 20
    inbound_rate_window_seconds: int = 60
    staleness_threshold_seconds: int = 7_200  # 2h
    conversation_lock_ttl_ms: int = 120_000
    conversation_lock_retry_delay_seconds: float = 2.0
    job_max_retries: int = 3

    # --- Send gateway pacing (DESIGN.md §5.6) ---
    send_min_delay_seconds: float = 3.0
    send_max_delay_seconds: float = 8.0
    send_burst: int = 3
    send_default_daily_cap: int = 500
    typing_seconds_per_char: float = 0.03
    typing_max_seconds: float = 12.0

    # --- Phase 1: platform ---
    # Browser origins allowed to call the API (dashboard). Prod: https://app.<domain>.
    cors_origins: list[str] = Field(
        default=["http://localhost:3002", "http://127.0.0.1:3002"]
    )
    # JWT lifetime for dashboard/ops login tokens (DESIGN.md §8).
    jwt_expiry_hours: int = 24
    # Auto-resume TTL for a paused conversation (DESIGN.md §5.5, default 6h).
    takeover_auto_resume_ttl_seconds: int = 21_600
    # Local fallback directory for raw knowledge uploads when MinIO is absent (§6, §12.3).
    knowledge_upload_dir: str = "/data/knowledge"

    # --- Phase 1: agent core ---
    # System-default provider/model, used when a tenant has no override (§4).
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str | None = None
    llm_api_key: str = "change-me"
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str | None = None
    embedding_api_key: str = "change-me"
    # --- Phase 2: voice (STT/TTS). Gemini's OpenAI-compat has no audio endpoints,
    # so these need an OpenAI/Groq-style key; unset api_key = voice disabled. ---
    stt_provider: str = "groq"
    stt_model: str = "whisper-large-v3"
    stt_base_url: str | None = None
    stt_api_key: str | None = None
    tts_provider: str = "openai"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    tts_format: str = "opus"  # WhatsApp voice = OPUS/OGG
    tts_base_url: str | None = None
    tts_api_key: str | None = None
    # When to reply with a voice note: "match" (only if the customer sent voice),
    # "always", or "never". Per-tenant override via tenant_config.providers.voice.
    voice_reply_mode: str = "match"
    # Reject inbound voice notes larger than this before STT (abuse/cost guard) —
    # a customer can't force an arbitrarily long transcription bill. 8 MB of
    # OPUS/OGG is ~40 min, well past any real voice message.
    max_inbound_audio_bytes: int = 8_000_000
    # Bytes→seconds estimate for metering inbound/outbound voice when the STT/TTS
    # response carries no duration (WhatsApp voice ≈ 16 kbps OPUS ≈ 2 KB/s).
    voice_bytes_per_second: int = 2_000
    # Provider adapter tuning (retries with exponential backoff, DESIGN.md §4).
    provider_timeout_seconds: float = 30.0
    provider_max_retries: int = 2
    provider_retry_base_seconds: float = 1.0

    # --- RAG (DESIGN.md §6) ---
    rag_top_k: int = 6
    rag_min_score: float = 0.5
    rag_chunk_tokens: int = 500
    rag_chunk_overlap_tokens: int = 50

    # --- Phase 3: agentic integrations (DESIGN.md §7) ---
    # One platform-wide Google OAuth client serves every tenant; each tenant's
    # refresh token is Fernet-encrypted per-row in ``integrations``. The same
    # client also backs "Sign in with Google" (its redirect URI is Auth.js's).
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    # Public origin Google redirects back to. Must match the Cloud console entry
    # exactly, or the flow dies with a bare ``redirect_uri_mismatch``.
    google_oauth_redirect_base: str = "http://localhost:8000"
    # Where the OAuth callback sends the browser once the grant is stored.
    dashboard_base_url: str = "http://localhost:3002"
    google_oauth_state_ttl_seconds: int = 600
    # Expire the cached access token this many seconds before Google would, so an
    # in-flight tool call never races the expiry.
    google_token_cache_skew_seconds: int = 120
    # Google Picker (browser-side sheet chooser) — Picker-restricted API key and
    # the Cloud project number.
    google_picker_api_key: str | None = None
    google_picker_app_id: str | None = None
    # Default timezone for calendar events when a tenant hasn't set one.
    google_default_timezone: str = "UTC"
    # Default duration (minutes) for a booked appointment when the model omits one.
    booking_default_duration_minutes: int = 30
    # Booking reminders (§5.7): the scheduler sends a confirmation + a reminder
    # this many hours before the appointment. Capped at 2 messages/booking.
    reminders_enabled: bool = True
    reminder_lookahead_hours: int = 24

    # --- Email (owner alerts, DESIGN.md §12.1) ---
    # Transport: "log" (dev — just logs), "resend" (HTTP API), or "smtp".
    email_provider: str = "log"
    email_from: str = "Qonvo <alerts@qonvo.local>"
    email_resend_api_key: str | None = None
    email_smtp_host: str | None = None
    email_smtp_port: int = 587
    email_smtp_user: str | None = None
    email_smtp_password: str | None = None
    email_smtp_starttls: bool = True

    # --- Observability ---
    # Expose GET /metrics in Prometheus text format (request + pipeline metrics).
    metrics_enabled: bool = True

    # --- Agent pipeline (DESIGN.md §5.4) ---
    history_window_messages: int = 20
    history_window_tokens: int = 4_000
    summary_refresh_turns: int = 10
    tool_loop_max_iterations: int = 5
    # Per-provider-per-model USD price per 1K tokens: {provider: {model: {input, output}}}.
    llm_pricing: dict[str, dict[str, dict[str, float]]] = Field(
        default_factory=lambda: {
            "openai": {
                "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
                "gpt-4o": {"input": 0.0025, "output": 0.01},
                "text-embedding-3-small": {"input": 0.00002, "output": 0.0},
            },
            "openrouter": {
                "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            },
            "groq": {
                "llama-3.1-8b-instant": {"input": 0.00005, "output": 0.00008},
            },
            "gemini": {
                # $/1K tokens. Keep the running model's id here or compute_cost
                # records $0.00 (it returns 0 on a pricing miss).
                "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
                "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
                "gemini-2.5-flash": {"input": 0.0003, "output": 0.0025},
                "gemini-embedding-001": {"input": 0.00015, "output": 0.0},
            },
        }
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
