from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_common.validation import validate_bounded_json
from tomiris_core_contracts.orchestration import AnalysisTaskRequest
from tomiris_core_contracts.signals import Bias
from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.identity import MarketType
from tomiris_market_data.models import DataQualityOutcome, MarketDataBundle, Timeframe, require_utc


class RoleLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    DISABLED = "DISABLED"


class TrendState(StrEnum):
    STRONG_UP = "STRONG_UP"
    UP = "UP"
    NEUTRAL = "NEUTRAL"
    DOWN = "DOWN"
    STRONG_DOWN = "STRONG_DOWN"


class MomentumState(StrEnum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


class VolatilityState(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class RoleDataRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument: Annotated[str, Field(pattern=r"^[A-Z0-9_./-]{2,32}$")]
    timeframe: Timeframe
    minimum_bars: Annotated[int, Field(ge=2, le=999)]
    max_data_age_seconds: Annotated[int, Field(ge=1, le=604_800)]
    data_type: MarketDataType = MarketDataType.OHLCV
    venue: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_-]{1,31}$")] = "BINANCE"
    market_type: MarketType = MarketType.SPOT
    preferred_provider: Annotated[str | None, Field(max_length=64)] = None
    required_fields: tuple[str, ...] = ("open", "high", "low", "close", "volume")

    @field_validator("required_fields")
    @classmethod
    def supported_fields(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {"open", "high", "low", "close", "volume"}
        if not values or not set(values).issubset(allowed):
            raise ValueError("required_fields contains an unsupported field")
        return values


class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    definition_version: Annotated[str, Field(pattern=r"^1$")] = "1"
    agent_id: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    role_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{2,63}$")]
    enabled: bool = True
    lifecycle: RoleLifecycle = RoleLifecycle.ACTIVE
    config_version: Annotated[str, Field(min_length=1, max_length=32)]
    runtime_contract_version: Annotated[str, Field(pattern=r"^1$")] = "1"
    analysis_schema_version: Annotated[str, Field(pattern=r"^1$")] = "1"
    supported_assets: Annotated[tuple[str, ...], Field(min_length=1, max_length=20)]
    capabilities: Annotated[tuple[str, ...], Field(min_length=1, max_length=20)]
    required_data: Annotated[tuple[RoleDataRequirement, ...], Field(min_length=1, max_length=50)]
    parameters: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=lambda: {"max_evidence_items": 16})
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("supported_assets")
    @classmethod
    def unique_assets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.upper() for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("supported_assets must be unique")
        return normalized

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("capabilities must be unique")
        return values

    @field_validator("parameters", "metadata")
    @classmethod
    def bounded_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_json(value, max_depth=6, max_items=100)

    @model_validator(mode="after")
    def validate_definition(self) -> AgentDefinition:
        if self.lifecycle == RoleLifecycle.DISABLED and self.enabled:
            raise ValueError("DISABLED role definition cannot be enabled")
        instruments = {item.instrument for item in self.required_data}
        if not instruments.issubset(set(self.supported_assets)):
            raise ValueError("required_data instrument must be a supported asset")
        keys = {
            (item.instrument, item.timeframe, item.market_type, item.data_type)
            for item in self.required_data
        }
        if len(keys) != len(self.required_data):
            raise ValueError("required_data entries must be unique")
        max_evidence = self.limits.get("max_evidence_items", 16)
        if max_evidence < 1 or max_evidence > 20:
            raise ValueError("max_evidence_items must be between 1 and 20")
        return self


class AnalysisContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task: AnalysisTaskRequest
    snapshot_id: UUID
    as_of: datetime

    _utc = field_validator("as_of")(require_utc)

    @model_validator(mode="after")
    def matching_snapshot(self) -> AnalysisContext:
        if self.task.snapshot_id != self.snapshot_id:
            raise ValueError("analysis context snapshot mismatch")
        return self


class AnalyticalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_type: Annotated[str, Field(min_length=1, max_length=64)]
    summary: Annotated[str, Field(min_length=1, max_length=1_000)]
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    instrument: Annotated[str, Field(min_length=2, max_length=32)]
    timeframe: Timeframe
    feature_name: Annotated[str, Field(min_length=1, max_length=64)]
    feature_version: Annotated[str, Field(min_length=1, max_length=32)]
    observed_at: datetime
    source_timestamp: datetime
    observation: Annotated[str, Field(min_length=1, max_length=500)]

    _utc = field_validator("observed_at", "source_timestamp")(require_utc)


class TimeframeAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    timeframe: Timeframe
    trend: TrendState
    momentum: MomentumState
    volatility: VolatilityState
    volume_state: Annotated[str, Field(pattern=r"^(RISING|NORMAL|FALLING)$")]
    score: Annotated[float, Field(ge=-1, le=1)]

    @field_validator("score")
    @classmethod
    def finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class AnalysisDataRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    instrument: Annotated[str, Field(min_length=2, max_length=32)]
    timeframe: Timeframe
    first_bar_at: datetime
    last_bar_at: datetime
    bar_count: Annotated[int, Field(ge=1, le=1_000)]

    _utc = field_validator("first_bar_at", "last_bar_at")(require_utc)

    @model_validator(mode="after")
    def validate_range(self) -> AnalysisDataRange:
        if self.first_bar_at > self.last_bar_at:
            raise ValueError("first bar must not follow last bar")
        return self


class AgentAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    analysis_schema_version: Annotated[str, Field(pattern=r"^1$")]
    role_id: str
    role_version: str
    config_version: str
    feature_pipeline_version: str
    snapshot_id: UUID
    asset: str
    bias: Bias
    confidence: Annotated[float, Field(ge=0, le=1)]
    data_quality: DataQualityOutcome
    reason_codes: Annotated[tuple[str, ...], Field(max_length=20)] = ()
    timeframe_states: Annotated[tuple[TimeframeAnalysis, ...], Field(max_length=20)] = ()
    evidence: Annotated[tuple[AnalyticalEvidence, ...], Field(max_length=20)] = ()
    data_ranges: Annotated[tuple[AnalysisDataRange, ...], Field(max_length=50)] = ()
    data_provider: str
    data_as_of: datetime
    analysis_as_of: datetime

    _utc = field_validator("data_as_of", "analysis_as_of")(require_utc)

    @field_validator("confidence")
    @classmethod
    def finite_confidence(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @model_validator(mode="after")
    def enforce_abstention(self) -> AgentAnalysisResult:
        invalid = self.data_quality in {
            DataQualityOutcome.INVALID,
            DataQualityOutcome.INSUFFICIENT,
        }
        if invalid and self.bias != Bias.ABSTAIN:
            raise ValueError("invalid/insufficient data must produce ABSTAIN")
        if self.bias == Bias.ABSTAIN and not self.reason_codes:
            raise ValueError("ABSTAIN requires a reason code")
        return self


class RoleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    context: AnalysisContext
    market_data: MarketDataBundle

    @model_validator(mode="after")
    def matching_snapshot_and_cutoff(self) -> RoleInput:
        if self.market_data.snapshot_id != self.context.snapshot_id:
            raise ValueError("market-data bundle snapshot mismatch")
        if self.market_data.as_of != self.context.as_of:
            raise ValueError("market-data cutoff mismatch")
        return self
