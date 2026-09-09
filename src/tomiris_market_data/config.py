from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarketDataPlaneSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOMIRIS_MARKET_", env_file=".env", extra="ignore")

    event_store_max_events: int = Field(default=10_000, ge=100, le=1_000_000)
    event_store_max_bytes: int = Field(default=32_000_000, ge=1_024, le=1_000_000_000)
    stream_queue_max_events: int = Field(default=2_000, ge=10, le=100_000)
    orderbook_buffer_max_events: int = Field(default=2_000, ge=10, le=100_000)
    orderbook_buffer_max_bytes: int = Field(default=8_000_000, ge=1_024, le=100_000_000)
    orderbook_buffer_max_duration_seconds: float = Field(default=30, gt=0, le=600)
    clock_degraded_threshold_ms: float = Field(default=500, gt=0, le=60_000)
    clock_unsafe_threshold_ms: float = Field(default=2_000, gt=0, le=120_000)
    stream_reconnect_base_seconds: float = Field(default=0.25, gt=0, le=30)
    stream_reconnect_max_seconds: float = Field(default=10, gt=0, le=300)
    stream_reconnect_max_attempts: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> MarketDataPlaneSettings:
        if self.clock_unsafe_threshold_ms <= self.clock_degraded_threshold_ms:
            raise ValueError("unsafe clock threshold must exceed degraded threshold")
        if self.stream_reconnect_max_seconds < self.stream_reconnect_base_seconds:
            raise ValueError("reconnect maximum must not be below base delay")
        return self
