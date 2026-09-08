from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from tomiris_market_data.cache import InMemoryMarketDataCache, MarketDataCache
from tomiris_market_data.errors import ProviderError
from tomiris_market_data.metrics import MarketDataMetrics
from tomiris_market_data.models import (
    MarketDataRequest,
    MarketDataSeries,
    MarketSummary,
    OHLCVBar,
    TickerSnapshot,
)

Sleep = Callable[[float], Awaitable[None]]
RandomValue = Callable[[], float]


class BinanceProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str = "https://api.binance.com"
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    read_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    max_attempts: int = Field(default=3, ge=1, le=5)
    retry_base_seconds: float = Field(default=0.25, gt=0, le=10)
    retry_max_seconds: float = Field(default=2.0, gt=0, le=30)
    max_response_bytes: int = Field(default=2_000_000, ge=1_024, le=10_000_000)
    max_concurrency: int = Field(default=4, ge=1, le=20)
    cache_ttl_seconds: int = Field(default=10, ge=1, le=300)
    allow_insecure_localhost: bool = False
    allowed_host_suffixes: tuple[str, ...] = ("binance.com", "binance.us")

    @model_validator(mode="after")
    def validate_endpoint(self) -> BinanceProviderSettings:
        try:
            parsed = urlsplit(self.base_url)
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("malformed Binance base URL") from exc
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("Binance base URL must be a credential-free origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Binance base URL must not contain path, query or fragment")
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (self.allow_insecure_localhost and local):
            raise ValueError("Binance public provider requires HTTPS")
        host = parsed.hostname.lower().rstrip(".")
        allowed = any(
            host == suffix.lstrip(".").lower() or host.endswith(f".{suffix.lstrip('.').lower()}")
            for suffix in self.allowed_host_suffixes
        )
        if not local and not allowed:
            raise ValueError("Binance public provider host is outside the allowlist")
        return self


class BinancePublicMarketDataProvider:
    """Bounded, retry-aware client for Binance public market-data endpoints only."""

    name = "binance-public"

    def __init__(
        self,
        settings: BinanceProviderSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: MarketDataCache | None = None,
        metrics: MarketDataMetrics | None = None,
        sleep: Sleep = asyncio.sleep,
        random_value: RandomValue = random.random,
    ) -> None:
        self.settings = settings or BinanceProviderSettings()
        self.transport = transport
        self.cache = cache or InMemoryMarketDataCache()
        self.metrics = metrics or MarketDataMetrics()
        self.sleep = sleep
        self.random_value = random_value
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrency)

    async def get_ohlcv(self, request: MarketDataRequest) -> MarketDataSeries:
        cache_key = (
            f"ohlcv:{request.instrument}:{request.timeframe.value}:"
            f"{request.minimum_bars}:{request.as_of.isoformat()}"
        )
        cached = await self.cache.get(cache_key, request.as_of)
        if cached is not None:
            return cached
        limit = min(1_000, request.minimum_bars + 1)
        payload, received_at = await self._request_json(
            "/api/v3/klines",
            {
                "symbol": request.instrument,
                "interval": request.timeframe.value,
                "limit": str(limit),
                "endTime": str(int(request.as_of.timestamp() * 1_000)),
            },
            request.instrument,
        )
        if not isinstance(payload, list):
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "klines response must be a list")
        bars: list[OHLCVBar] = []
        for raw in payload:
            if not isinstance(raw, list) or len(raw) < 7:
                raise ProviderError("PROVIDER_SCHEMA_ERROR", "malformed kline row")
            try:
                open_time = datetime.fromtimestamp(int(raw[0]) / 1_000, tz=UTC)
                close_time = datetime.fromtimestamp(int(raw[6]) / 1_000, tz=UTC)
                closed = close_time <= request.as_of
                if request.closed_only and not closed:
                    continue
                freshness = max(0.0, (request.as_of - close_time).total_seconds())
                bars.append(
                    OHLCVBar(
                        provider=self.name,
                        instrument=request.instrument,
                        timeframe=request.timeframe,
                        open_time=open_time,
                        close_time=close_time,
                        open=Decimal(str(raw[1])),
                        high=Decimal(str(raw[2])),
                        low=Decimal(str(raw[3])),
                        close=Decimal(str(raw[4])),
                        volume=Decimal(str(raw[5])),
                        received_at=received_at,
                        source_timestamp=close_time,
                        freshness_seconds=freshness,
                        provenance="binance:/api/v3/klines",
                        closed=closed,
                    )
                )
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid kline value") from exc
        if not bars:
            raise ProviderError("PROVIDER_EMPTY_RESPONSE", "no closed candles returned")
        selected = tuple(bars[-request.minimum_bars :])
        series = MarketDataSeries(
            provider=self.name,
            instrument=request.instrument,
            timeframe=request.timeframe,
            as_of=request.as_of,
            bars=selected,
        )
        await self.cache.put(
            cache_key,
            series,
            request.as_of,
            self.settings.cache_ttl_seconds,
        )
        return series

    async def get_ticker(self, instrument: str) -> TickerSnapshot:
        payload, received_at = await self._request_json(
            "/api/v3/ticker/price", {"symbol": instrument}, instrument
        )
        if not isinstance(payload, dict) or payload.get("symbol") != instrument:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "ticker identity mismatch")
        try:
            price = Decimal(str(payload["price"]))
        except (InvalidOperation, KeyError, TypeError) as exc:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid ticker") from exc
        return TickerSnapshot(
            provider=self.name,
            instrument=instrument,
            price=price,
            observed_at=received_at,
            received_at=received_at,
        )

    async def get_market_summary(self, instrument: str) -> MarketSummary:
        payload, received_at = await self._request_json(
            "/api/v3/ticker/24hr", {"symbol": instrument}, instrument
        )
        if not isinstance(payload, dict) or payload.get("symbol") != instrument:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "summary identity mismatch")
        try:
            price_change = Decimal(str(payload["priceChangePercent"]))
            quote_volume = Decimal(str(payload["quoteVolume"]))
        except (InvalidOperation, KeyError, TypeError) as exc:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid summary") from exc
        return MarketSummary(
            provider=self.name,
            instrument=instrument,
            price_change_percent=price_change,
            quote_volume=quote_volume,
            observed_at=received_at,
            received_at=received_at,
        )

    async def _request_json(
        self, path: str, params: dict[str, str], asset: str
    ) -> tuple[object, datetime]:
        timeout = httpx.Timeout(
            connect=self.settings.connect_timeout_seconds,
            read=self.settings.read_timeout_seconds,
            write=self.settings.read_timeout_seconds,
            pool=self.settings.connect_timeout_seconds,
        )
        last_error: Exception | None = None
        started = time.perf_counter()
        self.metrics.increment("market_data_requests_total", self.name, asset)
        try:
            async with self._semaphore:
                for attempt in range(1, self.settings.max_attempts + 1):
                    try:
                        async with httpx.AsyncClient(
                            base_url=self.settings.base_url,
                            timeout=timeout,
                            transport=self.transport,
                            headers={"User-Agent": "TOMIRIS-MarketData/0.3"},
                            follow_redirects=False,
                        ) as client:
                            async with client.stream("GET", path, params=params) as response:
                                if (
                                    400 <= response.status_code <= 499
                                    and response.status_code != 429
                                ):
                                    raise ProviderError(
                                        "PROVIDER_NON_RETRYABLE", f"HTTP {response.status_code}"
                                    )
                                if (
                                    response.status_code == 429
                                    or 500 <= response.status_code <= 599
                                ):
                                    raise httpx.HTTPStatusError(
                                        f"retryable HTTP {response.status_code}",
                                        request=response.request,
                                        response=response,
                                    )
                                response.raise_for_status()
                                content = bytearray()
                                async for chunk in response.aiter_bytes():
                                    content.extend(chunk)
                                    if len(content) > self.settings.max_response_bytes:
                                        raise ProviderError(
                                            "PROVIDER_RESPONSE_TOO_LARGE",
                                            "provider response exceeds configured limit",
                                        )
                        try:
                            payload = json.loads(content)
                        except json.JSONDecodeError as exc:
                            raise ProviderError(
                                "PROVIDER_SCHEMA_ERROR", "provider returned malformed JSON"
                            ) from exc
                        return payload, datetime.now(UTC)
                    except ProviderError:
                        self.metrics.increment("market_data_failures_total", self.name, asset)
                        raise
                    except (
                        httpx.TimeoutException,
                        httpx.TransportError,
                        httpx.HTTPStatusError,
                    ) as exc:
                        last_error = exc
                        if attempt == self.settings.max_attempts:
                            break
                        bounded = min(
                            self.settings.retry_max_seconds,
                            self.settings.retry_base_seconds * (2 ** (attempt - 1)),
                        )
                        delay = bounded * (0.5 + 0.5 * self.random_value())
                        if (
                            isinstance(exc, httpx.HTTPStatusError)
                            and exc.response.status_code == 429
                        ):
                            retry_after = exc.response.headers.get("Retry-After")
                            if retry_after is not None:
                                try:
                                    delay = min(
                                        self.settings.retry_max_seconds,
                                        max(delay, float(retry_after)),
                                    )
                                except ValueError:
                                    pass
                        await self.sleep(delay)
            self.metrics.increment("market_data_failures_total", self.name, asset)
            code = (
                "PROVIDER_TIMEOUT"
                if isinstance(last_error, httpx.TimeoutException)
                else "PROVIDER_ERROR"
            )
            raise ProviderError(code, "public market-data request failed") from last_error
        finally:
            self.metrics.observe_latency(self.name, asset, (time.perf_counter() - started) * 1_000)
