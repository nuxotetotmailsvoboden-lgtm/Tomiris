from __future__ import annotations

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import (
    FundingRateSnapshot,
    IndexPriceSnapshot,
    InstrumentMetadata,
    LastPriceSnapshot,
    LiquidationEvent,
    MarkPriceSnapshot,
    NormalizedMarketEvent,
    OHLCVWindow,
    OpenInterestSnapshot,
    OrderBookDelta,
    OrderBookSnapshot,
    SourceMetadata,
    TradeEvent,
)
from tomiris_market_data.identity import CanonicalInstrument
from tomiris_market_data.models import MarketDataSeries, TickerSnapshot
from tomiris_market_data.serialization import canonical_sha256
from tomiris_market_data.time import TimeSource

_OBSERVATION_DATA_TYPES = {
    "TRADE": MarketDataType.TRADES,
    "ORDER_BOOK_SNAPSHOT": MarketDataType.ORDER_BOOK_SNAPSHOT,
    "ORDER_BOOK_DELTA": MarketDataType.ORDER_BOOK_DELTA,
    "MARK_PRICE": MarketDataType.MARK_PRICE,
    "INDEX_PRICE": MarketDataType.INDEX_PRICE,
    "FUNDING_RATE": MarketDataType.FUNDING_RATE,
    "OPEN_INTEREST": MarketDataType.OPEN_INTEREST,
    "LIQUIDATION": MarketDataType.LIQUIDATION,
    "INSTRUMENT_METADATA": MarketDataType.INSTRUMENT_METADATA,
}


def ohlcv_series_to_event(
    series: MarketDataSeries,
    *,
    instrument: CanonicalInstrument,
    clock: TimeSource,
) -> NormalizedMarketEvent:
    if series.instrument != instrument.symbol:
        raise ValueError("legacy OHLCV series does not match canonical instrument")
    last_bar = series.bars[-1]
    received_at = max(bar.received_at for bar in series.bars)
    source = SourceMetadata(
        endpoint=last_bar.provenance,
        source_event_type="closed_ohlcv_window",
        source_schema_version="phase03.v1",
        normalizer_version="phase03-ohlcv-adapter.v1",
        provenance=last_bar.provenance,
    )
    observation = OHLCVWindow(
        provider=series.provider,
        instrument=instrument,
        exchange_timestamp=last_bar.close_time,
        received_at=received_at,
        source=source,
        timeframe=series.timeframe,
        bars=series.bars,
    )
    digest = canonical_sha256(series)
    return NormalizedMarketEvent(
        event_id=f"OHLCV:{instrument.instrument_id}:{series.timeframe.value}:{digest[:24]}",
        provider=series.provider,
        venue=instrument.venue,
        instrument=instrument,
        data_type=MarketDataType.OHLCV,
        event_time=last_bar.close_time,
        exchange_time=last_bar.close_time,
        received_at=received_at,
        processed_at=clock.now(),
        payload=observation,
        source=source,
    )


def ticker_to_event(
    ticker: TickerSnapshot,
    *,
    instrument: CanonicalInstrument,
    clock: TimeSource,
) -> NormalizedMarketEvent:
    if ticker.instrument != instrument.symbol:
        raise ValueError("legacy ticker does not match canonical instrument")
    source = SourceMetadata(
        endpoint="/api/v3/ticker/price",
        source_event_type="ticker",
        source_schema_version="phase03.v1",
        normalizer_version="phase03-ticker-adapter.v1",
        provenance="binance-public:/api/v3/ticker/price",
    )
    observation = LastPriceSnapshot(
        provider=ticker.provider,
        instrument=instrument,
        exchange_timestamp=ticker.observed_at,
        received_at=ticker.received_at,
        source=source,
        last_price=ticker.price,
    )
    digest = canonical_sha256(ticker)
    return NormalizedMarketEvent(
        event_id=f"TICKER:{instrument.instrument_id}:{digest[:24]}",
        provider=ticker.provider,
        venue=instrument.venue,
        instrument=instrument,
        data_type=MarketDataType.TICKER,
        event_time=ticker.observed_at,
        exchange_time=ticker.observed_at,
        received_at=ticker.received_at,
        processed_at=clock.now(),
        payload=observation,
        source=source,
    )


def observation_to_event(
    observation: TradeEvent
    | OrderBookSnapshot
    | OrderBookDelta
    | MarkPriceSnapshot
    | IndexPriceSnapshot
    | FundingRateSnapshot
    | OpenInterestSnapshot
    | LiquidationEvent
    | InstrumentMetadata,
    *,
    clock: TimeSource,
    data_type: MarketDataType | None = None,
) -> NormalizedMarketEvent:
    selected_type = data_type or _OBSERVATION_DATA_TYPES[observation.kind]
    if observation.kind == "TRADE" and selected_type not in {
        MarketDataType.TRADES,
        MarketDataType.AGGREGATE_TRADES,
    }:
        raise ValueError("trade observation data type mismatch")
    sequence = None
    if isinstance(observation, OrderBookDelta):
        sequence = observation.final_update_id
    elif isinstance(observation, OrderBookSnapshot):
        sequence = observation.last_update_id
    elif isinstance(observation, TradeEvent):
        sequence = observation.provider_sequence
    digest = canonical_sha256(observation)
    return NormalizedMarketEvent(
        event_id=f"{observation.kind}:{observation.instrument.instrument_id}:{digest[:24]}",
        provider=observation.provider,
        venue=observation.instrument.venue,
        instrument=observation.instrument,
        data_type=selected_type,
        event_time=observation.exchange_timestamp,
        exchange_time=observation.exchange_timestamp,
        received_at=observation.received_at,
        processed_at=clock.now(),
        sequence=sequence,
        payload=observation,
        source=observation.source,
    )
