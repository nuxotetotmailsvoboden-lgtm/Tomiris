from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import NormalizedMarketEvent
from tomiris_market_data.identity import CanonicalInstrument
from tomiris_market_data.models import DataQualityOutcome, DataQualityReport, require_utc
from tomiris_market_data.time import ClockDriftMeasurement, TimeSyncState


class QualityDimension(StrEnum):
    FRESHNESS = "freshness"
    COMPLETENESS = "completeness"
    SEQUENCE_INTEGRITY = "sequence_integrity"
    TEMPORAL_INTEGRITY = "temporal_integrity"
    SCHEMA_INTEGRITY = "schema_integrity"
    INSTRUMENT_INTEGRITY = "instrument_integrity"
    CROSS_STREAM_CONSISTENCY = "cross_stream_consistency"
    PROVIDER_HEALTH = "provider_health"
    CLOCK_INTEGRITY = "clock_integrity"


class QualityDimensionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: QualityDimension
    state: DataQualityOutcome
    reason_codes: Annotated[tuple[str, ...], Field(max_length=20)] = ()
    observed_value: float | None = None

    @field_validator("observed_value")
    @classmethod
    def finite_observed_value(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("quality observed value must be finite")
        return value


class MarketDataQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    overall_state: DataQualityOutcome
    dimensions: Annotated[tuple[QualityDimensionResult, ...], Field(min_length=1, max_length=20)]
    reason_codes: Annotated[tuple[str, ...], Field(max_length=50)] = ()
    observed_at: datetime
    instrument: CanonicalInstrument
    data_type: MarketDataType
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    safe_for_analysis: bool
    quality_policy_version: Annotated[str, Field(min_length=1, max_length=32)] = "market-quality.v1"

    _utc = field_validator("observed_at")(require_utc)

    @model_validator(mode="after")
    def enforce_veto(self) -> MarketDataQualityReport:
        if len({item.dimension for item in self.dimensions}) != len(self.dimensions):
            raise ValueError("quality dimensions must be unique")
        severity = {
            DataQualityOutcome.VALID: 0,
            DataQualityOutcome.DEGRADED: 1,
            DataQualityOutcome.INSUFFICIENT: 2,
            DataQualityOutcome.INVALID: 3,
        }
        expected = max(self.dimensions, key=lambda item: severity[item.state]).state
        if self.overall_state != expected:
            raise ValueError("overall quality state must match the worst dimension")
        unsafe_state = self.overall_state in {
            DataQualityOutcome.INVALID,
            DataQualityOutcome.INSUFFICIENT,
        }
        if unsafe_state and self.safe_for_analysis:
            raise ValueError("invalid or insufficient market data cannot be analysis-safe")
        return self


class MarketDataQualityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Annotated[str, Field(min_length=1, max_length=32)] = "market-quality.v1"
    max_age_seconds: float = Field(default=30, gt=0, le=604_800)
    degraded_age_ratio: float = Field(default=0.75, gt=0, lt=1)
    max_future_skew_seconds: float = Field(default=1, ge=0, le=60)


class MarketDataQualityEngine:
    _severity = {
        DataQualityOutcome.VALID: 0,
        DataQualityOutcome.DEGRADED: 1,
        DataQualityOutcome.INSUFFICIENT: 2,
        DataQualityOutcome.INVALID: 3,
    }

    def evaluate(
        self,
        *,
        instrument: CanonicalInstrument,
        data_type: MarketDataType,
        provider: str,
        observed_at: datetime,
        dimensions: tuple[QualityDimensionResult, ...],
        force_unsafe: bool = False,
    ) -> MarketDataQualityReport:
        require_utc(observed_at)
        if not dimensions:
            raise ValueError("quality evaluation requires dimensions")
        overall = max(dimensions, key=lambda item: self._severity[item.state]).state
        reasons = tuple(
            dict.fromkeys(reason for dimension in dimensions for reason in dimension.reason_codes)
        )
        safe = not force_unsafe and overall in {
            DataQualityOutcome.VALID,
            DataQualityOutcome.DEGRADED,
        }
        return MarketDataQualityReport(
            overall_state=overall,
            dimensions=dimensions,
            reason_codes=reasons,
            observed_at=observed_at,
            instrument=instrument,
            data_type=data_type,
            provider=provider,
            safe_for_analysis=safe,
        )

    def from_phase03_report(
        self,
        report: DataQualityReport,
        *,
        instrument: CanonicalInstrument,
        provider: str,
        observed_at: datetime,
    ) -> MarketDataQualityReport:
        dimension = QualityDimensionResult(
            dimension=QualityDimension.SCHEMA_INTEGRITY,
            state=report.outcome,
            reason_codes=report.reason_codes,
        )
        return self.evaluate(
            instrument=instrument,
            data_type=MarketDataType.OHLCV,
            provider=provider,
            observed_at=observed_at,
            dimensions=(dimension,),
        )

    def evaluate_event(
        self,
        event: NormalizedMarketEvent,
        *,
        observed_at: datetime,
        policy: MarketDataQualityPolicy | None = None,
        clock_drift: ClockDriftMeasurement | None = None,
        sequence_integrity: bool = True,
        provider_healthy: bool = True,
        complete: bool = True,
        cross_stream_consistent: bool = True,
    ) -> MarketDataQualityReport:
        require_utc(observed_at)
        selected = policy or MarketDataQualityPolicy()
        age = (observed_at - event.event_time).total_seconds()
        freshness_reason: tuple[str, ...]
        if age < -selected.max_future_skew_seconds:
            freshness = DataQualityOutcome.INVALID
            freshness_reason = ("EVENT_FROM_FUTURE",)
        elif age > selected.max_age_seconds:
            freshness = DataQualityOutcome.INVALID
            freshness_reason = ("DATA_STALE",)
        elif age > selected.max_age_seconds * selected.degraded_age_ratio:
            freshness = DataQualityOutcome.DEGRADED
            freshness_reason = ("DATA_NEAR_STALE",)
        else:
            freshness = DataQualityOutcome.VALID
            freshness_reason = ()
        temporal = (
            DataQualityOutcome.INVALID
            if event.exchange_time > event.received_at
            and (event.exchange_time - event.received_at).total_seconds()
            > selected.max_future_skew_seconds
            else DataQualityOutcome.VALID
        )
        clock_state = clock_drift.state if clock_drift is not None else TimeSyncState.HEALTHY
        clock_quality = {
            TimeSyncState.HEALTHY: DataQualityOutcome.VALID,
            TimeSyncState.DEGRADED: DataQualityOutcome.DEGRADED,
            TimeSyncState.UNSAFE: DataQualityOutcome.INVALID,
        }[clock_state]
        dimensions = (
            QualityDimensionResult(
                dimension=QualityDimension.FRESHNESS,
                state=freshness,
                reason_codes=freshness_reason,
                observed_value=max(0.0, age),
            ),
            QualityDimensionResult(
                dimension=QualityDimension.COMPLETENESS,
                state=DataQualityOutcome.VALID if complete else DataQualityOutcome.INSUFFICIENT,
                reason_codes=() if complete else ("DATA_INCOMPLETE",),
            ),
            QualityDimensionResult(
                dimension=QualityDimension.SEQUENCE_INTEGRITY,
                state=DataQualityOutcome.VALID
                if sequence_integrity
                else DataQualityOutcome.INVALID,
                reason_codes=() if sequence_integrity else ("SEQUENCE_GAP",),
            ),
            QualityDimensionResult(
                dimension=QualityDimension.TEMPORAL_INTEGRITY,
                state=temporal,
                reason_codes=()
                if temporal == DataQualityOutcome.VALID
                else ("TIME_ORDER_INVALID",),
            ),
            QualityDimensionResult(
                dimension=QualityDimension.SCHEMA_INTEGRITY,
                state=DataQualityOutcome.VALID,
            ),
            QualityDimensionResult(
                dimension=QualityDimension.INSTRUMENT_INTEGRITY,
                state=DataQualityOutcome.VALID,
            ),
            QualityDimensionResult(
                dimension=QualityDimension.CROSS_STREAM_CONSISTENCY,
                state=DataQualityOutcome.VALID
                if cross_stream_consistent
                else DataQualityOutcome.INVALID,
                reason_codes=() if cross_stream_consistent else ("CROSS_STREAM_INCONSISTENT",),
            ),
            QualityDimensionResult(
                dimension=QualityDimension.PROVIDER_HEALTH,
                state=DataQualityOutcome.VALID if provider_healthy else DataQualityOutcome.INVALID,
                reason_codes=() if provider_healthy else ("PROVIDER_UNHEALTHY",),
            ),
            QualityDimensionResult(
                dimension=QualityDimension.CLOCK_INTEGRITY,
                state=clock_quality,
                reason_codes=()
                if clock_state == TimeSyncState.HEALTHY
                else (f"CLOCK_DRIFT_{clock_state.value}",),
                observed_value=clock_drift.clock_offset_ms if clock_drift is not None else 0.0,
            ),
        )
        return self.evaluate(
            instrument=event.instrument,
            data_type=event.data_type,
            provider=event.provider,
            observed_at=observed_at,
            dimensions=dimensions,
            force_unsafe=clock_state == TimeSyncState.UNSAFE,
        )
