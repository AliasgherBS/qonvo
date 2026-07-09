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

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
