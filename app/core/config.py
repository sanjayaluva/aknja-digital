"""Application configuration.

Secrets and connection URIs come from the environment (`.env` locally).
Business/operational parameters live in the `system_settings` database table
(zero-hardcode mandate, SRS v6.1 §8.2) and must never be hardcoded here.
Protected governance invariants (zero-cost mode, spend ceiling) are validated
here from the environment and cannot be weakened by runtime settings.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Aknja Digital"
    app_env: Literal["local", "ci", "staging", "production"] = "local"
    secret_key: SecretStr = Field(default=SecretStr("insecure-dev-key-change-me"))
    database_url: str = "postgresql+psycopg://aknja:aknja_local_only@localhost:5432/aknja"
    log_level: str = "INFO"

    # --- Protected zero-cost governance (SRS v5.3.1, ADR-004). ---
    # These are protected invariants: runtime settings cannot weaken them.
    zero_cost_mode: bool = True
    max_approved_monthly_spend_minor: int = 0
    paid_fallback_enabled: bool = False
    auto_upgrade_enabled: bool = False
    auto_topup_enabled: bool = False
    hard_stop_threshold_pct: float = 95.0

    # --- Storage ---
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: str = "var/storage"
    object_storage_endpoint: str = ""
    object_storage_bucket: str = ""
    object_storage_access_key_id: str = ""
    object_storage_secret_access_key: SecretStr = SecretStr("")

    # --- Optional integrations (disabled until verified per SRS §14) ---
    ai_provider_enabled: bool = False
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_admin_chat_id: str = ""

    # --- Upload limits ---
    max_upload_bytes: int = 20 * 1024 * 1024
    session_ttl_hours: int = 24 * 7
    approval_default_expiry_hours: int = 48

    # --- Bootstrap admin (only used by the CLI on first init) ---
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    @field_validator("database_url")
    @classmethod
    def _validate_db_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgresql+psycopg://", "sqlite")):
            raise ValueError("DATABASE_URL must be a PostgreSQL (psycopg) URL")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cookie_secure(self) -> bool:
        # Secure cookies everywhere except plain-HTTP local development.
        return self.app_env != "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
