from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from tests.phase04_support import ETH_FUTURES, NOW

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import AggressorSide, LiquidationEvent, OrderBookDelta
from tomiris_market_data.normalization import BinanceFuturesEventNormalizer
from tomiris_market_data.streams import (
    ManagedMarketDataStream,
    StreamConnection,
    StreamSettings,
    StreamState,
)
from tomiris_market_data.time import DeterministicClock


def payloads() -> dict[str, object]:
    payload: object = json.loads(
        Path("tests/fixtures/market_data/binance_futures_ws.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
    return payload


def normalizer() -> BinanceFuturesEventNormalizer:
    return BinanceFuturesEventNormalizer(
        lambda symbol: ETH_FUTURES if symbol == "ETHUSDT" else (_ for _ in ()).throw(ValueError())
    )


def test_binance_wire_payloads_normalize_to_domain_contracts() -> None:
    raw = payloads()
    trade = normalizer().normalize(json.dumps(raw["trade"]), received_at=NOW, processed_at=NOW)
    depth = normalizer().normalize(json.dumps(raw["depth"]), received_at=NOW, processed_at=NOW)
    premium = normalizer().normalize(json.dumps(raw["premium"]), received_at=NOW, processed_at=NOW)
    liquidation = normalizer().normalize(
        json.dumps(raw["liquidation"]), received_at=NOW, processed_at=NOW
    )
    assert trade[0].data_type == MarketDataType.AGGREGATE_TRADES
    assert trade[0].payload.aggressor == AggressorSide.BUY
    assert isinstance(depth[0].payload, OrderBookDelta)
    assert depth[0].payload.previous_final_update_id == 100
    assert {event.data_type for event in premium} == {
        MarketDataType.MARK_PRICE,
        MarketDataType.INDEX_PRICE,
        MarketDataType.FUNDING_RATE,
    }
    assert isinstance(liquidation[0].payload, LiquidationEvent)
    assert "not inferred" in liquidation[0].payload.provider_semantics


class FixtureConnection:
    def __init__(self, messages: tuple[str, ...]) -> None:
        self.messages = messages
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes | str]:
        for message in self.messages:
            yield message

    async def close(self) -> None:
        self.closed = True


class FixtureConnector:
    def __init__(self, connections: list[FixtureConnection]) -> None:
        self.connections = connections
        self.calls = 0

    async def connect(self) -> StreamConnection:
        connection = self.connections[min(self.calls, len(self.connections) - 1)]
        self.calls += 1
        return connection


async def test_stream_real_lifecycle_reconnects_and_cleans_up() -> None:
    raw = json.dumps(payloads()["trade"])
    first = FixtureConnection((raw,))
    second = FixtureConnection((raw,))
    connector = FixtureConnector([first, second])

    async def no_sleep(_delay: float) -> None:
        await asyncio.sleep(0)

    stream = ManagedMarketDataStream(
        provider="binance-futures-public",
        market_type=ETH_FUTURES.market_type,
        data_type=MarketDataType.AGGREGATE_TRADES,
        connector=connector,
        normalizer=normalizer(),
        settings=StreamSettings(
            queue_max_events=10,
            reconnect_max_attempts=3,
            reconnect_base_seconds=0.001,
            reconnect_max_seconds=0.001,
        ),
        clock=DeterministicClock(NOW),
        sleep=no_sleep,
        random_value=lambda: 0,
    )
    await stream.start()
    iterator = stream.events()
    first_event = await anext(iterator)
    second_event = await anext(iterator)
    assert first_event == second_event
    assert connector.calls >= 2
    assert stream.health().state in {StreamState.LIVE, StreamState.RECONNECTING}
    await stream.close()
    assert first.closed and second.closed
    assert stream.health().state == StreamState.STOPPED
