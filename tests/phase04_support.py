from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import (
    MarkPriceSnapshot,
    NormalizedMarketEvent,
    OrderBookDelta,
    OrderBookLevel,
    OrderBookSnapshot,
    SourceMetadata,
)
from tomiris_market_data.identity import CanonicalInstrument

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
ETH_FUTURES = CanonicalInstrument.binance_usdt_m("ETHUSDT", "ETH")
ETH_SPOT = CanonicalInstrument.binance_spot("ETHUSDT", "ETH", "USDT")


def source(event_type: str = "fixture") -> SourceMetadata:
    return SourceMetadata(
        endpoint="fixture://phase04",
        source_event_type=event_type,
        source_schema_version="fixture.v1",
        normalizer_version="fixture-normalizer.v1",
        provenance=f"fixture:phase04:{event_type}",
    )


def book_snapshot(last_update_id: int = 100) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        provider="fixture-provider",
        instrument=ETH_FUTURES,
        exchange_timestamp=NOW,
        received_at=NOW,
        source=source("depthSnapshot"),
        last_update_id=last_update_id,
        bids=(
            OrderBookLevel(price=Decimal("100"), quantity=Decimal("2")),
            OrderBookLevel(price=Decimal("99"), quantity=Decimal("3")),
        ),
        asks=(
            OrderBookLevel(price=Decimal("101"), quantity=Decimal("2")),
            OrderBookLevel(price=Decimal("102"), quantity=Decimal("3")),
        ),
    )


def book_delta(
    first_id: int,
    final_id: int,
    *,
    previous_id: int | None = None,
    bid_price: str = "100",
    bid_quantity: str = "4",
) -> OrderBookDelta:
    return OrderBookDelta(
        provider="fixture-provider",
        instrument=ETH_FUTURES,
        exchange_timestamp=NOW,
        received_at=NOW,
        source=source("depthUpdate"),
        first_update_id=first_id,
        final_update_id=final_id,
        previous_final_update_id=previous_id,
        bids=(OrderBookLevel(price=Decimal(bid_price), quantity=Decimal(bid_quantity)),),
    )


def mark_event(
    *,
    event_id: str = "mark-1",
    price: str = "100",
    event_time: datetime = NOW,
    instrument: CanonicalInstrument = ETH_FUTURES,
) -> NormalizedMarketEvent:
    metadata = source("markPrice")
    observation = MarkPriceSnapshot(
        provider="fixture-provider",
        instrument=instrument,
        exchange_timestamp=event_time,
        received_at=event_time,
        source=metadata,
        mark_price=Decimal(price),
    )
    return NormalizedMarketEvent(
        event_id=event_id,
        provider="fixture-provider",
        venue="BINANCE",
        instrument=instrument,
        data_type=MarketDataType.MARK_PRICE,
        event_time=event_time,
        exchange_time=event_time,
        received_at=event_time,
        processed_at=event_time,
        payload=observation,
        source=metadata,
    )
