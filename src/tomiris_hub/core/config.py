from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    app_name: str = "TOMIRIS"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str
    tomiris_hub_ingest_key_id: str = Field(min_length=1, max_length=64)
    tomiris_hub_ingest_secret: SecretStr
    tomiris_hub_previous_key_id: str | None = None
    tomiris_hub_previous_secret: SecretStr | None = None
    auth_max_clock_skew_seconds: int = Field(default=60, ge=1, le=600)
    max_signal_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    max_signal_request_bytes: int = Field(default=65536, ge=1024, le=1048576)
    database_connect_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    rate_limit_enabled: bool = False
    rate_limit_per_agent: int = Field(default=60, ge=1)
    rate_limit_per_ip: int = Field(default=120, ge=1)
    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    notification_max_attempts: int = Field(default=5, ge=1, le=20)
    notification_base_retry_seconds: int = Field(default=5, ge=1, le=3600)
    notification_max_retry_seconds: int = Field(default=300, ge=1, le=86400)
    log_level: str = "INFO"

    @field_validator("tomiris_hub_ingest_secret")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("TOMIRIS_HUB_INGEST_SECRET must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_rotation(self) -> Settings:
        has_previous_id = bool(self.tomiris_hub_previous_key_id)
        has_previous_secret = self.tomiris_hub_previous_secret is not None
        if has_previous_id != has_previous_secret:
            raise ValueError("previous key ID and secret must be configured together")

        def unsafe_in_production(secret_value: str) -> bool:
            normalized = secret_value.strip().lower()
            unsafe_markers = (
                "change_me",
                "changeme",
                "placeholder",
                "replace-with",
                "development",
                "example",
                "test-secret",
            )
            unsafe_exact = {"0123456789abcdef0123456789abcdef"}
            repeated = bool(re.fullmatch(r"(.)\1{31,}", normalized))
            return (
                normalized in unsafe_exact
                or any(marker in normalized for marker in unsafe_markers)
                or repeated
            )

        secrets_to_validate = [self.tomiris_hub_ingest_secret.get_secret_value()]
        if self.tomiris_hub_previous_secret is not None:
            previous = self.tomiris_hub_previous_secret.get_secret_value()
            if len(previous) < 32:
                raise ValueError("previous ingest secret must contain at least 32 characters")
            secrets_to_validate.append(previous)
        if self.app_env == "production":
            if any(unsafe_in_production(secret) for secret in secrets_to_validate):
                raise ValueError("unsafe ingest secret prohibited in production")
        if self.telegram_enabled and not (self.telegram_bot_token and self.telegram_chat_id):
            raise ValueError("Telegram token and chat ID are required when Telegram is enabled")
        if self.notification_max_retry_seconds < self.notification_base_retry_seconds:
            raise ValueError("notification max retry must be >= base retry")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
