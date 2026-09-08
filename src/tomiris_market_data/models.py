from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def require_utc(value: datetime) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("timestamp must be UTC")
    return value


def finite_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("numeric values must be finite")
    return value


class Timeframe(StrEnum):
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    @property
    def seconds(self) -> int:
        return {"15m": 900, "1h": 3_600, "4h": 14_400, "1d": 86_400}[self.value]


class DataQualityOutcome(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"
    INSUFFICIENT = "INSUFFICIENT"


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    received_at: datetime
    source_timestamp: datetime
    freshness_seconds: Annotated[float, Field(ge=0)]
    provenance: Annotated[str, Field(min_length=1, max_length=256)]

    _utc = field_validator("received_at", "source_timestamp")(require_utc)

    @field_validator("freshness_seconds")
    @classmethod
    def finite_freshness(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("freshness must be finite")
        return value


class OHLCVBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    instrument: Annotated[str, Field(pattern=r"^[A-Z0-9_./-]{2,32}$")]
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    received_at: datetime
    source_timestamp: datetime
    freshness_seconds: Annotated[float, Field(ge=0)]
    provenance: Annotated[str, Field(min_length=1, max_length=256)]
    closed: bool = True

    _utc = field_validator("open_time", "close_time", "received_at", "source_timestamp")(
        require_utc
    )
    _finite = field_validator("open", "high", "low", "close", "volume")(finite_decimal)

    @field_validator("freshness_seconds")
    @classmethod
    def finite_freshness(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("freshness must be finite")
        return value

    @model_validator(mode="after")
    def validate_ohlcv(self) -> OHLCVBar:
        if self.open_time >= self.close_time:
            raise ValueError("open_time must precede close_time")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be the greatest OHLC value")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be the smallest OHLC value")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")
        return self


class MarketDataSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    instrument: Annotated[str, Field(pattern=r"^[A-Z0-9_./-]{2,32}$")]
    timeframe: Timeframe
    as_of: datetime
    bars: Annotated[tuple[OHLCVBar, ...], Field(min_length=1, max_length=1_000)]

    _utc = field_validator("as_of")(require_utc)

    @model_validator(mode="after")
    def validate_identity(self) -> MarketDataSeries:
        for bar in self.bars:
            if (
                bar.provider != self.provider
                or bar.instrument != self.instrument
                or bar.timeframe != self.timeframe
            ):
                raise ValueError("series contains a bar from another provider/instrument/timeframe")
        return self


class MarketDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instrument: Annotated[str, Field(pattern=r"^[A-Z0-9_./-]{2,32}$")]
    timeframe: Timeframe
    minimum_bars: Annotated[int, Field(ge=2, le=999)]
    as_of: datetime
    max_data_age_seconds: Annotated[int, Field(ge=1, le=604_800)]
    closed_only: bool = True

    _utc = field_validator("as_of")(require_utc)


class MarketDataBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot_id: UUID
    as_of: datetime
    series: Annotated[tuple[MarketDataSeries, ...], Field(min_length=1, max_length=50)]
    providers: Annotated[tuple[ProviderMetadata, ...], Field(min_length=1, max_length=50)]

    _utc = field_validator("as_of")(require_utc)

    def get_series(self, instrument: str, timeframe: Timeframe) -> MarketDataSeries:
        matches = [
            item
            for item in self.series
            if item.instrument == instrument.upper() and item.timeframe == timeframe
        ]
        if len(matches) != 1:
            raise KeyError(f"expected one series for {instrument}/{timeframe}, got {len(matches)}")
        return matches[0]


class TickerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    instrument: str
    price: Decimal
    observed_at: datetime
    received_at: datetime

    _utc = field_validator("observed_at", "received_at")(require_utc)
    _finite = field_validator("price")(finite_decimal)

    @model_validator(mode="after")
    def positive_price(self) -> TickerSnapshot:
        if self.price <= 0:
            raise ValueError("ticker price must be positive")
        return self


class MarketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    instrument: str
    price_change_percent: Decimal
    quote_volume: Decimal
    observed_at: datetime
    received_at: datetime

    _utc = field_validator("observed_at", "received_at")(require_utc)
    _finite = field_validator("price_change_percent", "quote_volume")(finite_decimal)

    @model_validator(mode="after")
    def non_negative_volume(self) -> MarketSummary:
        if self.quote_volume < 0:
            raise ValueError("quote volume must be non-negative")
        return self


class DataQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    outcome: DataQualityOutcome
    reason_codes: tuple[str, ...] = ()
    accepted_bars: int = 0
