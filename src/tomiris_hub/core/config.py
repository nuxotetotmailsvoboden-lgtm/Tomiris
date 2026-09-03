from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    rate_limit_enabled: bool = False
    rate_limit_per_agent: int = Field(default=60, ge=1)
    rate_limit_per_ip: int = Field(default=120, ge=1)
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
        if self.app_env == "production":
            bad = {"change_me", "test", "development", ""}
            if self.tomiris_hub_ingest_secret.get_secret_value().lower() in bad:
                raise ValueError("unsafe ingest secret prohibited in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
