from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    tomiris_agent_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    tomiris_agent_role: str = Field(min_length=1, max_length=64)
    tomiris_agent_capabilities: str
    tomiris_agent_supported_assets: str
    tomiris_hub_url: str
    tomiris_hub_key_id: str = Field(default="current", min_length=1, max_length=64)
    tomiris_hub_agent_secret: SecretStr
    tomiris_orchestrator_id: str = Field(
        default="TOMIRIS_ORCHESTRATOR", min_length=1, max_length=64
    )
    tomiris_orchestrator_command_key_id: str = Field(default="current", min_length=1, max_length=64)
    tomiris_orchestrator_command_secret: SecretStr
    tomiris_runtime_mode: Literal["test", "analytical"] = "test"
    tomiris_agent_definition_path: str | None = None
    runtime_version: str = "0.4.0"
    command_max_clock_skew_seconds: int = Field(default=60, ge=1, le=600)
    command_nonce_ttl_seconds: int = Field(default=600, ge=60, le=3_600)
    max_task_request_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    market_data_base_url: str = "https://api.binance.com"
    market_data_connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    market_data_read_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    market_data_max_attempts: int = Field(default=3, ge=1, le=5)
    market_data_retry_base_seconds: float = Field(default=0.25, gt=0, le=10)
    market_data_retry_max_seconds: float = Field(default=2.0, gt=0, le=30)
    market_data_max_response_bytes: int = Field(default=2_000_000, ge=1_024, le=10_000_000)
    market_data_max_concurrency: int = Field(default=4, ge=1, le=20)
    market_data_cache_ttl_seconds: int = Field(default=10, ge=1, le=300)
    market_data_allow_insecure_localhost: bool = False

    @model_validator(mode="after")
    def validate_secrets(self) -> AgentRuntimeSettings:
        if len(self.tomiris_hub_agent_secret.get_secret_value()) < 32:
            raise ValueError("Hub agent secret must contain at least 32 characters")
        if len(self.tomiris_orchestrator_command_secret.get_secret_value()) < 32:
            raise ValueError("command secret must contain at least 32 characters")
        if (
            self.tomiris_hub_agent_secret.get_secret_value()
            == self.tomiris_orchestrator_command_secret.get_secret_value()
        ):
            raise ValueError("Hub ingest and command secrets must differ")
        if not self.tomiris_hub_url.startswith(("http://", "https://")):
            raise ValueError("TOMIRIS_HUB_URL must be HTTP(S)")
        if self.tomiris_runtime_mode == "analytical" and self.tomiris_agent_definition_path is None:
            raise ValueError("analytical runtime requires TOMIRIS_AGENT_DEFINITION_PATH")
        return self

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(
            item.strip() for item in self.tomiris_agent_capabilities.split(",") if item.strip()
        )

    @property
    def supported_assets(self) -> tuple[str, ...]:
        return tuple(
            item.strip().upper()
            for item in self.tomiris_agent_supported_assets.split(",")
            if item.strip()
        )
