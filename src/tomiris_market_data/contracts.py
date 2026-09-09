from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.identity import CanonicalInstrument
from tomiris_market_data.models import OHLCVBar, Timeframe, finite_decimal, require_utc


class BookSide(StrEnum):
    BID = "BID"
    ASK = "ASK"


class AggressorSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    UNKNOWN = "UNKNOWN"


class OrderBookLevel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    price: Decimal
    quantity: Decimal

    _finite = field_validator("price", "quantity")(finite_decimal)

    @model_validator(mode="after")
    def valid_level(self) -> OrderBookLevel:
        if self.price <= 0:
            raise ValueError("order-book price must be positive")
        if self.quantity < 0:
            raise ValueError("order-book quantity must be non-negative")
        return self


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: Annotated[str, Field(min_length=1, max_length=256)]
    stream: Annotated[str | None, Field(max_length=256)] = None
    source_event_type: Annotated[str, Field(min_length=1, max_length=64)]
    source_schema_version: Annotated[str, Field(min_length=1, max_length=32)] = "provider-current"
    normalizer_version: Annotated[str, Field(min_length=1, max_length=32)]
    provenance: Annotated[str, Field(min_length=1, max_length=256)]


class MarketObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Annotated[str, Field(min_length=1, max_length=64)]
    instrument: CanonicalInstrument
    exchange_timestamp: datetime
    received_at: datetime
    schema_version: Annotated[str, Field(pattern=r"^1$")] = "1"
    source: SourceMetadata

    _utc = field_validator("exchange_timestamp", "received_at")(require_utc)


class OHLCVWindow(MarketObservation):
    kind: Literal["OHLCV"] = "OHLCV"
    timeframe: Timeframe
    bars: Annotated[tuple[OHLCVBar, ...], Field(min_length=1, max_length=1_000)]

    @model_validator(mode="after")
    def valid_window(self) -> OHLCVWindow:
        if any(
            bar.instrument != self.instrument.symbol
            or bar.timeframe != self.timeframe
            or bar.provider != self.provider
            or not bar.closed
            for bar in self.bars
        ):
            raise ValueError("OHLCV window identity mismatch or contains an open candle")
        if tuple(sorted(self.bars, key=lambda bar: bar.open_time)) != self.bars:
            raise ValueError("OHLCV window bars must be time ordered")
        if self.exchange_timestamp != self.bars[-1].close_time:
            raise ValueError("OHLCV exchange timestamp must match final candle close")
        return self


class LastPriceSnapshot(MarketObservation):
    kind: Literal["LAST_PRICE"] = "LAST_PRICE"
    last_price: Decimal

    _finite = field_validator("last_price")(finite_decimal)

    @model_validator(mode="after")
    def positive_last(self) -> LastPriceSnapshot:
        if self.last_price <= 0:
            raise ValueError("last price must be positive")
        return self


class TradeEvent(MarketObservation):
    kind: Literal["TRADE"] = "TRADE"
    trade_id: Annotated[str, Field(min_length=1, max_length=128)]
    price: Decimal
    quantity: Decimal
    aggressor: AggressorSide = AggressorSide.UNKNOWN
    provider_sequence: int | None = Field(default=None, ge=0)

    _finite = field_validator("price", "quantity")(finite_decimal)

    @model_validator(mode="after")
    def valid_trade(self) -> TradeEvent:
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("trade price and quantity must be positive")
        return self


class OrderBookSnapshot(MarketObservation):
    kind: Literal["ORDER_BOOK_SNAPSHOT"] = "ORDER_BOOK_SNAPSHOT"
    last_update_id: int = Field(ge=0)
    bids: Annotated[tuple[OrderBookLevel, ...], Field(max_length=5_000)]
    asks: Annotated[tuple[OrderBookLevel, ...], Field(max_length=5_000)]

    @model_validator(mode="after")
    def valid_book(self) -> OrderBookSnapshot:
        if not self.bids or not self.asks:
            raise ValueError("order-book snapshot requires both sides")
        if list(self.bids) != sorted(self.bids, key=lambda level: level.price, reverse=True):
            raise ValueError("bids must be sorted descending")
        if list(self.asks) != sorted(self.asks, key=lambda level: level.price):
            raise ValueError("asks must be sorted ascending")
        if self.bids[0].price >= self.asks[0].price:
            raise ValueError("best bid must be below best ask")
        return self


class OrderBookDelta(MarketObservation):
    kind: Literal["ORDER_BOOK_DELTA"] = "ORDER_BOOK_DELTA"
    first_update_id: int = Field(ge=0)
    final_update_id: int = Field(ge=0)
    previous_final_update_id: int | None = Field(default=None, ge=0)
    bids: Annotated[tuple[OrderBookLevel, ...], Field(max_length=5_000)] = ()
    asks: Annotated[tuple[OrderBookLevel, ...], Field(max_length=5_000)] = ()

    @model_validator(mode="after")
    def ordered_sequence(self) -> OrderBookDelta:
        if self.final_update_id < self.first_update_id:
            raise ValueError("final update ID must not precede first update ID")
        return self


class MarkPriceSnapshot(MarketObservation):
    kind: Literal["MARK_PRICE"] = "MARK_PRICE"
    mark_price: Decimal

    _finite = field_validator("mark_price")(finite_decimal)

    @model_validator(mode="after")
    def positive_mark(self) -> MarkPriceSnapshot:
        if self.mark_price <= 0:
            raise ValueError("mark price must be positive")
        return self


class IndexPriceSnapshot(MarketObservation):
    kind: Literal["INDEX_PRICE"] = "INDEX_PRICE"
    index_price: Decimal

    _finite = field_validator("index_price")(finite_decimal)

    @model_validator(mode="after")
    def positive_index(self) -> IndexPriceSnapshot:
        if self.index_price <= 0:
            raise ValueError("index price must be positive")
        return self


class FundingRateSnapshot(MarketObservation):
    kind: Literal["FUNDING_RATE"] = "FUNDING_RATE"
    rate: Decimal
    funding_at: datetime | None = None
    next_funding_at: datetime | None = None

    _finite = field_validator("rate")(finite_decimal)

    @field_validator("funding_at", "next_funding_at")
    @classmethod
    def optional_utc(cls, value: datetime | None) -> datetime | None:
        return require_utc(value) if value is not None else None


class OpenInterestSnapshot(MarketObservation):
    kind: Literal["OPEN_INTEREST"] = "OPEN_INTEREST"
    value: Decimal
    unit: Annotated[str, Field(min_length=1, max_length=32)]
    context: Annotated[str, Field(min_length=1, max_length=128)]

    _finite = field_validator("value")(finite_decimal)

    @model_validator(mode="after")
    def non_negative_open_interest(self) -> OpenInterestSnapshot:
        if self.value < 0:
            raise ValueError("open interest must be non-negative")
        return self


class LiquidationEvent(MarketObservation):
    kind: Literal["LIQUIDATION"] = "LIQUIDATION"
    event_id: Annotated[str, Field(min_length=1, max_length=128)]
    side: AggressorSide = AggressorSide.UNKNOWN
    price: Decimal
    quantity: Decimal
    average_price: Decimal | None = None
    provider_semantics: Annotated[str, Field(min_length=1, max_length=128)]

    _finite = field_validator("price", "quantity")(finite_decimal)

    @field_validator("average_price")
    @classmethod
    def optional_finite(cls, value: Decimal | None) -> Decimal | None:
        return finite_decimal(value) if value is not None else None

    @model_validator(mode="after")
    def valid_liquidation(self) -> LiquidationEvent:
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("liquidation price and quantity must be positive")
        if self.average_price is not None and self.average_price <= 0:
            raise ValueError("average liquidation price must be positive")
        return self


class InstrumentMetadata(MarketObservation):
    kind: Literal["INSTRUMENT_METADATA"] = "INSTRUMENT_METADATA"
    status: Annotated[str, Field(min_length=1, max_length=32)]
    price_precision: int = Field(ge=0, le=30)
    quantity_precision: int = Field(ge=0, le=30)
    tick_size: Decimal
    step_size: Decimal
    contract_size: Decimal | None = None
    metadata_version: Annotated[str, Field(min_length=1, max_length=64)]

    _finite = field_validator("tick_size", "step_size")(finite_decimal)

    @field_validator("contract_size")
    @classmethod
    def optional_contract_size(cls, value: Decimal | None) -> Decimal | None:
        return finite_decimal(value) if value is not None else None

    @model_validator(mode="after")
    def positive_rules(self) -> InstrumentMetadata:
        if self.tick_size <= 0 or self.step_size <= 0:
            raise ValueError("tick and step sizes must be positive")
        if self.contract_size is not None and self.contract_size <= 0:
            raise ValueError("contract size must be positive")
        return self


MarketEventPayload = Annotated[
    OHLCVWindow
    | LastPriceSnapshot
    | TradeEvent
    | OrderBookSnapshot
    | OrderBookDelta
    | MarkPriceSnapshot
    | IndexPriceSnapshot
    | FundingRateSnapshot
    | OpenInterestSnapshot
    | LiquidationEvent
    | InstrumentMetadata,
    Field(discriminator="kind"),
]


class NormalizedMarketEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: Annotated[str, Field(min_length=1, max_length=128)]
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    venue: Annotated[str, Field(min_length=1, max_length=32)]
    instrument: CanonicalInstrument
    data_type: MarketDataType
    event_time: datetime
    exchange_time: datetime
    received_at: datetime
    processed_at: datetime
    sequence: int | None = Field(default=None, ge=0)
    payload: MarketEventPayload
    schema_version: Annotated[str, Field(pattern=r"^1$")] = "1"
    source: SourceMetadata

    _utc = field_validator("event_time", "exchange_time", "received_at", "processed_at")(
        require_utc
    )

    @property
    def instrument_id(self) -> str:
        return self.instrument.instrument_id

    @model_validator(mode="after")
    def validate_lineage(self) -> NormalizedMarketEvent:
        expected = {
            "OHLCV": {MarketDataType.OHLCV},
            "LAST_PRICE": {MarketDataType.TICKER},
            "TRADE": {MarketDataType.TRADES, MarketDataType.AGGREGATE_TRADES},
            "ORDER_BOOK_SNAPSHOT": {MarketDataType.ORDER_BOOK_SNAPSHOT},
            "ORDER_BOOK_DELTA": {MarketDataType.ORDER_BOOK_DELTA},
            "MARK_PRICE": {MarketDataType.MARK_PRICE},
            "INDEX_PRICE": {MarketDataType.INDEX_PRICE},
            "FUNDING_RATE": {MarketDataType.FUNDING_RATE},
            "OPEN_INTEREST": {MarketDataType.OPEN_INTEREST},
            "LIQUIDATION": {MarketDataType.LIQUIDATION},
            "INSTRUMENT_METADATA": {MarketDataType.INSTRUMENT_METADATA},
        }
        if self.data_type not in expected[self.payload.kind]:
            raise ValueError("payload kind does not match market data type")
        if (
            self.provider != self.payload.provider
            or self.venue != self.instrument.venue
            or self.instrument != self.payload.instrument
            or self.source != self.payload.source
        ):
            raise ValueError("event envelope lineage mismatch")
        if self.processed_at < self.received_at:
            raise ValueError("processed time cannot precede receive time")
        timestamps = [self.event_time, self.exchange_time, self.payload.exchange_timestamp]
        if any(not math.isfinite(timestamp.timestamp()) for timestamp in timestamps):
            raise ValueError("event timestamp must be finite")
        return self
