from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_market_data.models import require_utc


class TimeSource(Protocol):
    def now(self) -> datetime: ...


class SystemUTCClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class DeterministicClock:
    current: datetime

    def __post_init__(self) -> None:
        require_utc(self.current)

    def now(self) -> datetime:
        return self.current

    def set(self, value: datetime) -> None:
        require_utc(value)
        self.current = value


class TimeSyncState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNSAFE = "UNSAFE"


class ClockDriftPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = "clock-drift.v1"
    degraded_threshold_ms: float = Field(default=500, gt=0)
    unsafe_threshold_ms: float = Field(default=2_000, gt=0)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> ClockDriftPolicy:
        if self.unsafe_threshold_ms <= self.degraded_threshold_ms:
            raise ValueError("unsafe clock threshold must exceed degraded threshold")
        return self


class ClockDriftMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    measured_at: datetime
    exchange_time: datetime
    local_midpoint: datetime
    clock_offset_ms: float
    round_trip_ms: float = Field(ge=0)
    state: TimeSyncState
    policy_version: str

    _utc = field_validator("measured_at", "exchange_time", "local_midpoint")(require_utc)

    @property
    def safe_for_snapshot(self) -> bool:
        return self.state != TimeSyncState.UNSAFE


class ClockDriftMonitor:
    def __init__(self, policy: ClockDriftPolicy | None = None) -> None:
        self.policy = policy or ClockDriftPolicy()

    def measure(
        self,
        *,
        provider: str,
        exchange_time: datetime,
        request_started_at: datetime,
        response_received_at: datetime,
    ) -> ClockDriftMeasurement:
        require_utc(exchange_time)
        require_utc(request_started_at)
        require_utc(response_received_at)
        if response_received_at < request_started_at:
            raise ValueError("response time cannot precede request start")
        round_trip_ms = (response_received_at - request_started_at).total_seconds() * 1_000
        midpoint = request_started_at + (response_received_at - request_started_at) / 2
        offset_ms = (exchange_time - midpoint).total_seconds() * 1_000
        magnitude = abs(offset_ms)
        if magnitude >= self.policy.unsafe_threshold_ms:
            state = TimeSyncState.UNSAFE
        elif magnitude >= self.policy.degraded_threshold_ms:
            state = TimeSyncState.DEGRADED
        else:
            state = TimeSyncState.HEALTHY
        return ClockDriftMeasurement(
            provider=provider,
            measured_at=response_received_at,
            exchange_time=exchange_time,
            local_midpoint=midpoint,
            clock_offset_ms=offset_ms,
            round_trip_ms=round_trip_ms,
            state=state,
            policy_version=self.policy.policy_version,
        )
