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
    agent_auth_mode: Literal["shared", "derived"] = "shared"
    tomiris_hub_ingest_key_id: str = Field(min_length=1, max_length=64)
    tomiris_hub_ingest_secret: SecretStr | None = None
    tomiris_hub_previous_key_id: str | None = None
    tomiris_hub_previous_secret: SecretStr | None = None
    tomiris_hub_agent_master_secret: SecretStr | None = None
    tomiris_hub_agent_previous_master_secret: SecretStr | None = None
    tomiris_orchestrator_agent_master_secret: SecretStr | None = None
    orchestrator_command_key_id: str = Field(default="current", min_length=1, max_length=64)
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
    orchestrator_enabled: bool = False
    orchestrator_instance_id: str = Field(default="orchestrator-local", min_length=1, max_length=64)
    orchestrator_dispatch_batch_size: int = Field(default=20, ge=1, le=500)
    orchestrator_max_in_flight: int = Field(default=20, ge=1, le=500)
    orchestrator_poll_interval_seconds: float = Field(default=1.0, ge=0.05, le=60.0)
    agent_connect_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    agent_ack_timeout_seconds: float = Field(default=10.0, ge=0.1, le=300.0)
    agent_cold_start_grace_seconds: float = Field(default=60.0, ge=0.0, le=900.0)
    agent_signal_timeout_seconds: int = Field(default=300, ge=1, le=86_400)
    agent_max_dispatch_attempts: int = Field(default=5, ge=1, le=20)
    agent_retry_base_seconds: int = Field(default=5, ge=1, le=3_600)
    agent_retry_max_seconds: int = Field(default=300, ge=1, le=86_400)
    agent_circuit_failure_threshold: int = Field(default=3, ge=1, le=100)
    agent_circuit_open_seconds: int = Field(default=120, ge=1, le=86_400)
    agent_endpoint_allowed_host_suffixes: str = ".hf.space,.huggingface.co"
    log_level: str = "INFO"

    @field_validator(
        "tomiris_hub_ingest_secret",
        "tomiris_hub_previous_secret",
        "tomiris_hub_agent_master_secret",
        "tomiris_hub_agent_previous_master_secret",
        "tomiris_orchestrator_agent_master_secret",
    )
    @classmethod
    def validate_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("configured secrets must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_rotation(self) -> Settings:
        has_previous_id = bool(self.tomiris_hub_previous_key_id)
        if self.agent_auth_mode == "shared":
            if self.tomiris_hub_ingest_secret is None:
                raise ValueError("shared auth mode requires TOMIRIS_HUB_INGEST_SECRET")
            if has_previous_id != (self.tomiris_hub_previous_secret is not None):
                raise ValueError("previous key ID and shared secret must be configured together")
        else:
            if self.tomiris_hub_agent_master_secret is None:
                raise ValueError("derived auth mode requires TOMIRIS_HUB_AGENT_MASTER_SECRET")
            if has_previous_id != (self.tomiris_hub_agent_previous_master_secret is not None):
                raise ValueError("previous key ID and master secret must be configured together")

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

        secrets_to_validate = [
            item.get_secret_value()
            for item in (
                self.tomiris_hub_ingest_secret,
                self.tomiris_hub_previous_secret,
                self.tomiris_hub_agent_master_secret,
                self.tomiris_hub_agent_previous_master_secret,
                self.tomiris_orchestrator_agent_master_secret,
            )
            if item is not None
        ]
        if self.app_env == "production":
            if any(unsafe_in_production(secret) for secret in secrets_to_validate):
                raise ValueError("unsafe ingest secret prohibited in production")
            if self.orchestrator_enabled and self.tomiris_orchestrator_agent_master_secret is None:
                raise ValueError("orchestrator command master secret is required")
        if (
            self.tomiris_hub_agent_master_secret
            and self.tomiris_orchestrator_agent_master_secret
            and self.tomiris_hub_agent_master_secret.get_secret_value()
            == self.tomiris_orchestrator_agent_master_secret.get_secret_value()
        ):
            raise ValueError("Hub ingest and orchestrator command roots must differ")
        if self.telegram_enabled and not (self.telegram_bot_token and self.telegram_chat_id):
            raise ValueError("Telegram token and chat ID are required when Telegram is enabled")
        if self.notification_max_retry_seconds < self.notification_base_retry_seconds:
            raise ValueError("notification max retry must be >= base retry")
        if self.agent_retry_max_seconds < self.agent_retry_base_seconds:
            raise ValueError("agent max retry must be >= base retry")
        return self

    @property
    def allowed_agent_host_suffixes(self) -> tuple[str, ...]:
        return tuple(
            part.strip().lower()
            for part in self.agent_endpoint_allowed_host_suffixes.split(",")
            if part.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
