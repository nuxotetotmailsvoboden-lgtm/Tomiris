from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from tests.phase04_support import ETH_FUTURES, ETH_SPOT

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.errors import ProviderError
from tomiris_market_data.futures import (
    BinanceFuturesProviderSettings,
    BinancePublicFuturesMarketDataProvider,
)
from tomiris_market_data.models import MarketDataRequest, Timeframe
from tomiris_market_data.time import DeterministicClock

AS_OF = datetime(2024, 1, 1, 5, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def fixtures() -> dict[str, object]:
    payload: object = json.loads(
        Path("tests/fixtures/market_data/binance_futures_rest.json").read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
    return payload


def provider(handler: object) -> BinancePublicFuturesMarketDataProvider:
    assert callable(handler)
    return BinancePublicFuturesMarketDataProvider(
        BinanceFuturesProviderSettings(max_attempts=1),
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        clock=DeterministicClock(RECEIVED_AT),
    )


async def test_public_futures_derivatives_contracts_are_distinct_and_typed() -> None:
    data = fixtures()

    def handler(request: httpx.Request) -> httpx.Response:
        name = {
            "/fapi/v1/premiumIndex": "premiumIndex",
            "/fapi/v1/openInterest": "openInterest",
            "/fapi/v1/depth": "depth",
            "/fapi/v1/exchangeInfo": "exchangeInfo",
            "/fapi/v1/time": "serverTime",
        }[request.url.path]
        assert "signature" not in request.url.params
        assert "X-MBX-APIKEY" not in request.headers
        return httpx.Response(200, json=data[name])

    client = provider(handler)
    mark, index, funding = await client.get_premium_index(ETH_FUTURES)
    open_interest = await client.get_open_interest(ETH_FUTURES)
    book = await client.get_order_book_snapshot(ETH_FUTURES)
    metadata = await client.get_instrument_metadata(ETH_FUTURES)
    server_time, received_at = await client.get_server_time()
    assert mark.mark_price != index.index_price
    assert funding.rate.as_tuple().exponent < 0
    assert open_interest.unit == "BASE_ASSET_CONTRACTS"
    assert book.last_update_id == 100
    assert metadata.tick_size.as_tuple().exponent == -2
    assert server_time == datetime(2024, 1, 1, 1, 0, tzinfo=UTC)
    assert received_at == RECEIVED_AT
    assert MarketDataType.OPEN_INTEREST in client.capabilities.data_types


async def test_futures_provider_uses_futures_ohlcv_endpoint_and_closed_candles() -> None:
    klines: object = json.loads(
        Path("tests/fixtures/market_data/binance_klines_sample.json").read_text(encoding="utf-8")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/fapi/v1/klines"
        return httpx.Response(200, json=klines)

    result = await provider(handler).get_ohlcv(
        MarketDataRequest(
            instrument="ETHUSDT",
            timeframe=Timeframe.H1,
            minimum_bars=4,
            as_of=AS_OF,
            max_data_age_seconds=7_200,
        )
    )
    assert len(result.bars) == 4
    assert result.provider == "binance-futures-public"
    assert all(bar.closed and bar.close_time <= AS_OF for bar in result.bars)


async def test_futures_provider_rejects_cross_market_identity_and_bad_schema() -> None:
    client = provider(lambda _request: httpx.Response(200, json={}))
    with pytest.raises(ProviderError) as mismatch:
        await client.get_open_interest(ETH_SPOT)
    assert mismatch.value.code == "INSTRUMENT_MISMATCH"
    with pytest.raises(ProviderError) as schema:
        await client.get_open_interest(ETH_FUTURES)
    assert schema.value.code == "PROVIDER_SCHEMA_ERROR"
