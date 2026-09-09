from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tomiris_market_data.identity import MarketType


class MarketDataType(StrEnum):
    OHLCV = "OHLCV"
    TICKER = "TICKER"
    TRADES = "TRADES"
    AGGREGATE_TRADES = "AGGREGATE_TRADES"
    ORDER_BOOK_SNAPSHOT = "ORDER_BOOK_SNAPSHOT"
    ORDER_BOOK_DELTA = "ORDER_BOOK_DELTA"
    MARK_PRICE = "MARK_PRICE"
    INDEX_PRICE = "INDEX_PRICE"
    FUNDING_RATE = "FUNDING_RATE"
    OPEN_INTEREST = "OPEN_INTEREST"
    LIQUIDATION = "LIQUIDATION"
    INSTRUMENT_METADATA = "INSTRUMENT_METADATA"
    SERVER_TIME = "SERVER_TIME"


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{2,63}$")]
    venue: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_-]{1,31}$")]
    market_types: Annotated[tuple[MarketType, ...], Field(min_length=1, max_length=20)]
    data_types: Annotated[tuple[MarketDataType, ...], Field(min_length=1, max_length=50)]
    schema_version: Annotated[str, Field(pattern=r"^1$")] = "1"

    @field_validator("market_types", "data_types")
    @classmethod
    def unique_values(cls, values: tuple[object, ...]) -> tuple[object, ...]:
        if len(set(values)) != len(values):
            raise ValueError("provider capabilities must be unique")
        return values

    def supports(self, market_type: MarketType, data_type: MarketDataType) -> bool:
        return market_type in self.market_types and data_type in self.data_types
