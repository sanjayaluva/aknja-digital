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

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # alias'd fields (telegram_admin_chat_id) stay constructible by field
        # name — tests and internal callers rely on that.
        populate_by_name=True,
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

    # --- Backup & recovery (v5.3.2 §5A, docs/22) ---
    backup_dir: str = "var/backups"
    pg_bin_dir: str = ""  # empty: auto-discover (pgserver bundle, then PATH)

    # --- Optional integrations (disabled until verified per SRS §14) ---
    ai_provider_enabled: bool = False
    telegram_bot_token: SecretStr = SecretStr("")
    # TELEGRAM_ADMIN_CHAT_ID is the documented name (docs/39); the founder's
    # credential sheet uses TELEGRAM_FOUNDER_CHAT_ID — accept both, no restart
    # of the sheet's vocabulary required.
    telegram_admin_chat_id: str = Field(
        default="",
        validation_alias=AliasChoices("telegram_admin_chat_id", "telegram_founder_chat_id"),
    )

    # --- Layer-1 free LLM provider credentials (SRS §9, v5.3.2 §5C).
    # Keys alone enable nothing: the registry must also hold a FREE_VERIFIED,
    # enabled provider product before the inference layer will admit calls. ---
    gemini_api_keys: SecretStr = SecretStr("")          # comma-separated
    groq_api_keys: SecretStr = SecretStr("")            # comma-separated
    github_models_token: SecretStr = SecretStr("")
    cloudflare_api_token: SecretStr = SecretStr("")     # Workers AI (+ Pages)
    cloudflare_account_id: str = ""                     # same account as R2
    openrouter_api_key: SecretStr = SecretStr("")       # only :free model slugs
    mistral_api_key: SecretStr = SecretStr("")          # La Plateforme free plan
    llm_default_timeout_s: int = 20

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
