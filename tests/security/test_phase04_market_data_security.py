from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.phase04_support import ETH_FUTURES, NOW

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import OrderBookLevel
from tomiris_market_data.errors import DataValidationError, ProviderError
from tomiris_market_data.futures import BinanceFuturesProviderSettings
from tomiris_market_data.network_security import StaticHostResolver
from tomiris_market_data.normalization import BinanceFuturesEventNormalizer
from tomiris_market_data.stream_security import BinanceStreamEndpointPolicy
from tomiris_market_data.streams import ManagedMarketDataStream, StreamConnection, StreamSettings
from tomiris_market_data.time import DeterministicClock


@pytest.mark.parametrize(
    "url",
    [
        "http://fapi.binance.com",
        "https://user:password@fapi.binance.com",
        "https://evil.example",
        "https://fapi.binance.com/private",
        "https://127.0.0.1",
    ],
)
def test_rest_endpoint_policy_fails_closed(url: str) -> None:
    with pytest.raises(ValidationError):
        BinanceFuturesProviderSettings(base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "ws://fstream.binance.com/stream",
        "wss://user:password@fstream.binance.com/stream",
        "wss://evil.example/stream",
        "wss://fstream.binance.com/arbitrary",
        "wss://127.0.0.1/stream",
    ],
)
def test_websocket_endpoint_policy_fails_closed(url: str) -> None:
    with pytest.raises(ValidationError):
        BinanceStreamEndpointPolicy(base_url=url)


def test_stream_subscriptions_are_bounded_and_not_arbitrary_urls() -> None:
    policy = BinanceStreamEndpointPolicy(max_streams=100)
    names = tuple(f"asset{index}@aggtrade" for index in range(100))
    url = policy.combined_url(names)
    assert url.startswith("wss://fstream.binance.com/stream?streams=")
    with pytest.raises(ValueError):
        policy.combined_url(names + ("overflow@trade",))
    with pytest.raises(ValueError):
        policy.combined_url(("https://evil.example",))


def test_public_provider_configuration_has_no_secret_or_account_surface() -> None:
    field_names = set(BinanceFuturesProviderSettings.model_fields)
    forbidden = {"api_key", "api_secret", "private_key", "account_token", "trading_key"}
    assert field_names.isdisjoint(forbidden)


def test_untrusted_stream_payload_is_bounded_and_schema_validated() -> None:
    normalizer = BinanceFuturesEventNormalizer(lambda _symbol: ETH_FUTURES, max_message_bytes=1024)
    with pytest.raises(DataValidationError) as oversized:
        normalizer.normalize(b" " * 1025, received_at=NOW, processed_at=NOW)
    assert oversized.value.code == "STREAM_MESSAGE_TOO_LARGE"
    with pytest.raises(DataValidationError) as malformed:
        normalizer.normalize("{broken", received_at=NOW, processed_at=NOW)
    assert malformed.value.code == "MALFORMED_PAYLOAD"


class BurstConnection:
    closed = False

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        message = json.dumps(
            {
                "e": "aggTrade",
                "E": 1704070800100,
                "s": "ETHUSDT",
                "a": 1,
                "p": "100",
                "q": "1",
                "T": 1704070800100,
                "m": False,
            }
        )
        yield message
        yield message

    async def close(self) -> None:
        self.closed = True


class BurstConnector:
    connection = BurstConnection()

    async def connect(self) -> StreamConnection:
        return self.connection


async def test_stream_queue_overflow_fails_closed_instead_of_unbounded_growth() -> None:
    stream = ManagedMarketDataStream(
        provider="binance-futures-public",
        market_type=ETH_FUTURES.market_type,
        data_type=MarketDataType.AGGREGATE_TRADES,
        connector=BurstConnector(),
        normalizer=BinanceFuturesEventNormalizer(lambda _symbol: ETH_FUTURES),
        settings=StreamSettings(
            queue_max_events=1,
            reconnect_max_attempts=1,
            reconnect_base_seconds=0.001,
            reconnect_max_seconds=0.001,
        ),
        clock=DeterministicClock(NOW),
    )
    await stream.start()
    assert stream._runner is not None
    await asyncio.wait_for(stream._runner, timeout=1)
    assert stream.health().state.value == "FAILED"
    assert stream.health().reason_code == "RECONNECT_EXHAUSTED"
    assert stream._queue.qsize() <= 1
    await stream.close()


async def test_dns_rebinding_to_private_or_link_local_address_is_rejected() -> None:
    for address in ("127.0.0.1", "10.0.0.8", "169.254.169.254", "::1"):
        with pytest.raises(ProviderError) as caught:
            await StaticHostResolver((address,)).validate("fapi.binance.com", 443)
        assert caught.value.code == "PROVIDER_DNS_UNSAFE"
    await StaticHostResolver(("8.8.8.8",)).validate("fapi.binance.com", 443)


def test_untrusted_numeric_values_have_finite_domain_bounds() -> None:
    with pytest.raises(ValidationError):
        OrderBookLevel(price=Decimal("1e51"), quantity=Decimal("1"))
    with pytest.raises(ValidationError):
        OrderBookLevel(price=Decimal("NaN"), quantity=Decimal("1"))
