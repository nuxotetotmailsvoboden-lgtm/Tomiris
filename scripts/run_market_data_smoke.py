from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

from tomiris_market_data.adapters import observation_to_event
from tomiris_market_data.binance import BinancePublicMarketDataProvider
from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.futures import BinancePublicFuturesMarketDataProvider
from tomiris_market_data.identity import CanonicalInstrument
from tomiris_market_data.models import MarketDataRequest, Timeframe
from tomiris_market_data.orderbook import OrderBookSynchronizer
from tomiris_market_data.quality import MarketDataQualityEngine, MarketDataQualityPolicy
from tomiris_market_data.snapshot import (
    SnapshotRequirement,
    SnapshotRequirementItem,
    VerifiedMarketSnapshotBuilder,
)
from tomiris_market_data.store import InMemoryRecentMarketEventStore
from tomiris_market_data.time import ClockDriftMonitor, SystemUTCClock


async def main() -> None:
    clock = SystemUTCClock()
    spot = BinancePublicMarketDataProvider(clock=clock)
    futures = BinancePublicFuturesMarketDataProvider(clock=clock)
    store = InMemoryRecentMarketEventStore(max_events=500, max_bytes=5_000_000)
    quality_engine = MarketDataQualityEngine()
    reports = {}
    requirements = []
    result: dict[str, object] = {"markets": {}, "trade_execution": "DISABLED"}
    request_started = clock.now()
    exchange_time, response_received = await futures.get_server_time()
    drift = ClockDriftMonitor().measure(
        provider=futures.name,
        exchange_time=exchange_time,
        request_started_at=request_started,
        response_received_at=response_received,
    )
    for base in ("BTC", "ETH", "SOL"):
        symbol = f"{base}USDT"
        instrument = CanonicalInstrument.binance_usdt_m(symbol, base)
        as_of = clock.now()
        spot_series = await spot.get_ohlcv(
            MarketDataRequest(
                instrument=symbol,
                timeframe=Timeframe.M15,
                minimum_bars=2,
                as_of=as_of,
                max_data_age_seconds=3_600,
            )
        )
        mark, index, funding = await futures.get_premium_index(instrument)
        open_interest = await futures.get_open_interest(instrument)
        book = await futures.get_order_book_snapshot(instrument, limit=100)
        book_view = await OrderBookSynchronizer(instrument, futures.name, max_depth=100).bootstrap(
            book
        )
        observations = (mark, index, funding, open_interest, book)
        for observation in observations:
            event = observation_to_event(observation, clock=clock)
            await store.append(event)
            reports[event.event_id] = quality_engine.evaluate_event(
                event,
                observed_at=clock.now(),
                policy=MarketDataQualityPolicy(max_age_seconds=120),
                clock_drift=drift,
            )
            requirements.append(
                SnapshotRequirementItem(
                    instrument=instrument,
                    data_type=event.data_type,
                    required=True,
                    max_age_seconds=120,
                    minimum_depth=20
                    if event.data_type == MarketDataType.ORDER_BOOK_SNAPSHOT
                    else None,
                )
            )
        result["markets"][symbol] = {  # type: ignore[index]
            "spot_ohlcv": "VALID" if spot_series.bars else "INVALID",
            "mark": str(mark.mark_price),
            "index": str(index.index_price),
            "funding": str(funding.rate),
            "open_interest": str(open_interest.value),
            "book": book_view.state.value,
        }
    snapshot_as_of = clock.now()
    snapshot = await VerifiedMarketSnapshotBuilder(store, clock=clock).build(
        snapshot_id=uuid4(),
        as_of=snapshot_as_of,
        requirement=SnapshotRequirement(
            items=tuple(requirements),
            max_temporal_skew_seconds=120,
        ),
        quality_reports=reports,
        clock_measurements=(drift,),
    )
    result["clock"] = {
        "offset_ms": drift.clock_offset_ms,
        "round_trip_ms": drift.round_trip_ms,
        "state": drift.state.value,
    }
    result["snapshot"] = {
        "snapshot_id": str(snapshot.manifest.snapshot_id),
        "as_of": snapshot.manifest.as_of.isoformat(),
        "quality": snapshot.manifest.quality_state.value,
        "safe_for_analysis": snapshot.manifest.safe_for_analysis,
        "fingerprint": snapshot.manifest.content_fingerprint,
    }
    result["captured_within_seconds"] = (
        snapshot_as_of - request_started + timedelta(0)
    ).total_seconds()
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
