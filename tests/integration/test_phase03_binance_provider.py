from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tomiris_market_data.binance import (
    BinanceProviderSettings,
    BinancePublicMarketDataProvider,
)
from tomiris_market_data.errors import ProviderError
from tomiris_market_data.models import MarketDataRequest, Timeframe

AS_OF = datetime(2024, 1, 1, 5, 0, tzinfo=UTC)


def request(**changes: object) -> MarketDataRequest:
    values: dict[str, object] = {
        "instrument": "ETHUSDT",
        "timeframe": Timeframe.H1,
        "minimum_bars": 4,
        "as_of": AS_OF,
        "max_data_age_seconds": 7_200,
    }
    values.update(changes)
    return MarketDataRequest.model_validate(values)


def settings(**changes: object) -> BinanceProviderSettings:
    values: dict[str, object] = {
        "max_attempts": 3,
        "retry_base_seconds": 0.001,
        "retry_max_seconds": 0.002,
    }
    values.update(changes)
    return BinanceProviderSettings.model_validate(values)


def fixture_payload() -> object:
    return json.loads(
        Path("tests/fixtures/market_data/binance_klines_sample.json").read_text(encoding="utf-8")
    )


async def test_recorded_public_klines_normalize_and_cache() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["User-Agent"] == "TOMIRIS-MarketData/0.3"
        assert request.url.params["symbol"] == "ETHUSDT"
        return httpx.Response(200, json=fixture_payload())

    provider = BinancePublicMarketDataProvider(settings(), transport=httpx.MockTransport(handler))
    first = await provider.get_ohlcv(request())
    second = await provider.get_ohlcv(request())
    assert first == second
    assert calls == 1
    assert len(first.bars) == 4
    assert first.instrument == "ETHUSDT"
    assert all(bar.closed for bar in first.bars)
    assert (
        provider.metrics.counters[("market_data_requests_total", "binance-public", "ETHUSDT")] == 1
    )
    assert (
        len(provider.metrics.observations[("market_data_latency", "binance-public", "ETHUSDT")])
        == 1
    )


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"not": "a-list"}, "PROVIDER_SCHEMA_ERROR"),
        ([[1, 2]], "PROVIDER_SCHEMA_ERROR"),
        ([], "PROVIDER_EMPTY_RESPONSE"),
    ],
)
async def test_provider_rejects_malformed_schema(payload: object, code: str) -> None:
    provider = BinancePublicMarketDataProvider(
        settings(max_attempts=1),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)),
    )
    with pytest.raises(ProviderError) as caught:
        await provider.get_ohlcv(request())
    assert caught.value.code == code


async def test_provider_rejects_malformed_json_and_oversized_response() -> None:
    malformed = BinancePublicMarketDataProvider(
        settings(max_attempts=1),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"{broken")),
    )
    with pytest.raises(ProviderError) as malformed_error:
        await malformed.get_ohlcv(request())
    assert malformed_error.value.code == "PROVIDER_SCHEMA_ERROR"

    oversized = BinancePublicMarketDataProvider(
        settings(max_attempts=1, max_response_bytes=1_024),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"[" + b" " * 1_024 + b"]")
        ),
    )
    with pytest.raises(ProviderError) as oversized_error:
        await oversized.get_ohlcv(request())
    assert oversized_error.value.code == "PROVIDER_RESPONSE_TOO_LARGE"


@pytest.mark.parametrize("retry_status", [429, 500, 503])
async def test_rate_limit_and_selected_5xx_use_bounded_retry(retry_status: int) -> None:
    calls = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(retry_status)
        return httpx.Response(200, json=fixture_payload())

    async def sleep(delay: float) -> None:
        delays.append(delay)

    provider = BinancePublicMarketDataProvider(
        settings(),
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        random_value=lambda: 0.0,
    )
    result = await provider.get_ohlcv(request())
    assert result.bars
    assert calls == 2
    assert delays == [0.0005]


async def test_rate_limit_honors_bounded_retry_after() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json=fixture_payload())

    async def sleep(delay: float) -> None:
        delays.append(delay)

    provider = BinancePublicMarketDataProvider(
        settings(retry_max_seconds=0.5),
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        random_value=lambda: 0.0,
    )
    await provider.get_ohlcv(request())
    assert delays == [0.5]


async def test_timeout_retries_are_bounded_and_normalized() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("fixture timeout", request=request)

    async def no_sleep(_delay: float) -> None:
        return None

    provider = BinancePublicMarketDataProvider(
        settings(max_attempts=2),
        transport=httpx.MockTransport(handler),
        sleep=no_sleep,
    )
    with pytest.raises(ProviderError) as caught:
        await provider.get_ohlcv(request())
    assert caught.value.code == "PROVIDER_TIMEOUT"
    assert calls == 2


async def test_non_retryable_auth_failure_is_not_retried() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403)

    provider = BinancePublicMarketDataProvider(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as caught:
        await provider.get_ohlcv(request())
    assert caught.value.code == "PROVIDER_NON_RETRYABLE"
    assert calls == 1


async def test_open_candle_after_cutoff_is_excluded() -> None:
    payload = fixture_payload()
    assert isinstance(payload, list)
    future_open = int((AS_OF + timedelta(hours=1)).timestamp() * 1_000)
    payload.append([future_open, "105", "107", "104", "106", "1500", future_open + 3_599_999])
    provider = BinancePublicMarketDataProvider(
        settings(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload)),
    )
    result = await provider.get_ohlcv(request())
    assert len(result.bars) == 4
    assert all(bar.close_time <= AS_OF for bar in result.bars)
