from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from tomiris_market_data.binance import (
    BinanceProviderSettings,
    BinancePublicMarketDataProvider,
    RandomValue,
    Sleep,
)
from tomiris_market_data.cache import MarketDataCache
from tomiris_market_data.capabilities import MarketDataType, ProviderCapabilities
from tomiris_market_data.contracts import (
    FundingRateSnapshot,
    IndexPriceSnapshot,
    InstrumentMetadata,
    MarkPriceSnapshot,
    OpenInterestSnapshot,
    OrderBookLevel,
    OrderBookSnapshot,
    SourceMetadata,
)
from tomiris_market_data.errors import ProviderError
from tomiris_market_data.identity import CanonicalInstrument, MarketType
from tomiris_market_data.metrics import MarketDataMetrics
from tomiris_market_data.models import MarketDataRequest, MarketDataSeries, OHLCVBar
from tomiris_market_data.network_security import HostResolver
from tomiris_market_data.time import TimeSource


class BinanceFuturesProviderSettings(BinanceProviderSettings):
    base_url: str = "https://fapi.binance.com"
    allowed_host_suffixes: tuple[str, ...] = ("binance.com",)


class BinancePublicFuturesMarketDataProvider(BinancePublicMarketDataProvider):
    """Public-only Binance USDT-M REST adapter; no credential surface exists."""

    name = "binance-futures-public"

    def __init__(
        self,
        settings: BinanceFuturesProviderSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: MarketDataCache | None = None,
        metrics: MarketDataMetrics | None = None,
        sleep: Sleep = asyncio.sleep,
        random_value: RandomValue = random.random,
        clock: TimeSource | None = None,
        resolver: HostResolver | None = None,
    ) -> None:
        super().__init__(
            settings or BinanceFuturesProviderSettings(),
            transport=transport,
            cache=cache,
            metrics=metrics,
            sleep=sleep,
            random_value=random_value,
            clock=clock,
            resolver=resolver,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.name,
            venue="BINANCE",
            market_types=(MarketType.USDT_M_FUTURES,),
            data_types=(
                MarketDataType.OHLCV,
                MarketDataType.ORDER_BOOK_SNAPSHOT,
                MarketDataType.MARK_PRICE,
                MarketDataType.INDEX_PRICE,
                MarketDataType.FUNDING_RATE,
                MarketDataType.OPEN_INTEREST,
                MarketDataType.INSTRUMENT_METADATA,
                MarketDataType.SERVER_TIME,
            ),
        )

    async def get_ohlcv(self, request: MarketDataRequest) -> MarketDataSeries:
        payload, received_at = await self._request_json(
            "/fapi/v1/klines",
            {
                "symbol": request.instrument,
                "interval": request.timeframe.value,
                "limit": str(min(1_000, request.minimum_bars + 1)),
                "endTime": str(int(request.as_of.timestamp() * 1_000)),
            },
            request.instrument,
        )
        if not isinstance(payload, list):
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "futures klines must be a list")
        bars: list[OHLCVBar] = []
        for raw in payload:
            if not isinstance(raw, list) or len(raw) < 7:
                raise ProviderError("PROVIDER_SCHEMA_ERROR", "malformed futures kline row")
            try:
                open_time = _timestamp(raw[0])
                close_time = _timestamp(raw[6])
                closed = close_time <= request.as_of
                if request.closed_only and not closed:
                    continue
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
                        freshness_seconds=max(0.0, (request.as_of - close_time).total_seconds()),
                        provenance="binance:/fapi/v1/klines",
                        closed=closed,
                    )
                )
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid futures kline") from exc
        if not bars:
            raise ProviderError("PROVIDER_EMPTY_RESPONSE", "no closed futures candles returned")
        return MarketDataSeries(
            provider=self.name,
            instrument=request.instrument,
            timeframe=request.timeframe,
            as_of=request.as_of,
            bars=tuple(bars[-request.minimum_bars :]),
        )

    async def get_server_time(self) -> tuple[datetime, datetime]:
        payload, received_at = await self._request_json("/fapi/v1/time", {}, "SERVER_TIME")
        data = _mapping(payload, "server time")
        try:
            return _timestamp(data["serverTime"]), received_at
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid server time") from exc

    async def get_premium_index(
        self, instrument: CanonicalInstrument
    ) -> tuple[MarkPriceSnapshot, IndexPriceSnapshot, FundingRateSnapshot]:
        self._require_usdt_m(instrument)
        payload, received_at = await self._request_json(
            "/fapi/v1/premiumIndex", {"symbol": instrument.symbol}, instrument.symbol
        )
        data = _mapping(payload, "premium index")
        if data.get("symbol") != instrument.symbol:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "premium-index identity mismatch")
        try:
            exchange_at = _timestamp(data["time"])
            next_funding_ms = _as_int(data["nextFundingTime"])
            next_funding = _timestamp(next_funding_ms) if next_funding_ms > 0 else None
            source = self._source("/fapi/v1/premiumIndex", "premiumIndex")
            common = {
                "provider": self.name,
                "instrument": instrument,
                "exchange_timestamp": exchange_at,
                "received_at": received_at,
                "source": source,
            }
            return (
                MarkPriceSnapshot(mark_price=Decimal(str(data["markPrice"])), **common),
                IndexPriceSnapshot(index_price=Decimal(str(data["indexPrice"])), **common),
                FundingRateSnapshot(
                    rate=Decimal(str(data["lastFundingRate"])),
                    next_funding_at=next_funding,
                    **common,
                ),
            )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid premium-index data") from exc

    async def get_open_interest(self, instrument: CanonicalInstrument) -> OpenInterestSnapshot:
        self._require_usdt_m(instrument)
        payload, received_at = await self._request_json(
            "/fapi/v1/openInterest", {"symbol": instrument.symbol}, instrument.symbol
        )
        data = _mapping(payload, "open interest")
        if data.get("symbol") != instrument.symbol:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "open-interest identity mismatch")
        try:
            return OpenInterestSnapshot(
                provider=self.name,
                instrument=instrument,
                exchange_timestamp=_timestamp(data["time"]),
                received_at=received_at,
                source=self._source("/fapi/v1/openInterest", "openInterest"),
                value=Decimal(str(data["openInterest"])),
                unit="BASE_ASSET_CONTRACTS",
                context="Binance USDT-M contract quantity; not quote notional",
            )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid open interest") from exc

    async def get_order_book_snapshot(
        self, instrument: CanonicalInstrument, *, limit: int = 1_000
    ) -> OrderBookSnapshot:
        self._require_usdt_m(instrument)
        if limit not in {5, 10, 20, 50, 100, 500, 1_000}:
            raise ValueError("unsupported bounded Binance depth limit")
        payload, received_at = await self._request_json(
            "/fapi/v1/depth",
            {"symbol": instrument.symbol, "limit": str(limit)},
            instrument.symbol,
        )
        data = _mapping(payload, "order book")
        try:
            return OrderBookSnapshot(
                provider=self.name,
                instrument=instrument,
                exchange_timestamp=received_at,
                received_at=received_at,
                source=self._source("/fapi/v1/depth", "depthSnapshot"),
                last_update_id=_as_int(data["lastUpdateId"]),
                bids=_levels(data["bids"], reverse=True),
                asks=_levels(data["asks"], reverse=False),
            )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid order-book snapshot") from exc

    async def get_instrument_metadata(self, instrument: CanonicalInstrument) -> InstrumentMetadata:
        self._require_usdt_m(instrument)
        payload, received_at = await self._request_json("/fapi/v1/exchangeInfo", {}, "METADATA")
        data = _mapping(payload, "exchange info")
        symbols = data.get("symbols")
        if not isinstance(symbols, list):
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "exchange symbols must be a list")
        selected = next(
            (
                item
                for item in symbols
                if isinstance(item, dict) and item.get("symbol") == instrument.symbol
            ),
            None,
        )
        if selected is None:
            raise ProviderError("PROVIDER_EMPTY_RESPONSE", "instrument metadata unavailable")
        try:
            filters = selected["filters"]
            if not isinstance(filters, list):
                raise TypeError
            price_filter = _filter(filters, "PRICE_FILTER")
            lot_filter = _filter(filters, "LOT_SIZE")
            exchange_at = _timestamp(data["serverTime"])
            return InstrumentMetadata(
                provider=self.name,
                instrument=instrument,
                exchange_timestamp=exchange_at,
                received_at=received_at,
                source=self._source("/fapi/v1/exchangeInfo", "exchangeInfo"),
                status=str(selected["status"]),
                price_precision=_as_int(selected["pricePrecision"]),
                quantity_precision=_as_int(selected["quantityPrecision"]),
                tick_size=Decimal(str(price_filter["tickSize"])),
                step_size=Decimal(str(lot_filter["stepSize"])),
                metadata_version=str(int(exchange_at.timestamp() * 1_000)),
            )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ProviderError("PROVIDER_SCHEMA_ERROR", "invalid instrument metadata") from exc

    def _require_usdt_m(self, instrument: CanonicalInstrument) -> None:
        if instrument.venue != "BINANCE" or instrument.market_type != MarketType.USDT_M_FUTURES:
            raise ProviderError("INSTRUMENT_MISMATCH", "provider requires Binance USDT-M identity")

    @staticmethod
    def _source(endpoint: str, event_type: str) -> SourceMetadata:
        return SourceMetadata(
            endpoint=endpoint,
            source_event_type=event_type,
            normalizer_version="binance-futures-rest.v1",
            provenance=f"binance-public:{endpoint}",
        )


def _mapping(payload: object, label: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ProviderError("PROVIDER_SCHEMA_ERROR", f"{label} response must be an object")
    return payload


def _timestamp(value: object) -> datetime:
    return datetime.fromtimestamp(_as_int(value) / 1_000, tz=UTC)


def _as_int(value: object) -> int:
    return int(str(value))


def _levels(value: object, *, reverse: bool) -> tuple[OrderBookLevel, ...]:
    if not isinstance(value, list) or len(value) > 5_000:
        raise TypeError("invalid order-book levels")
    levels: list[OrderBookLevel] = []
    for raw in value:
        if not isinstance(raw, list) or len(raw) < 2:
            raise TypeError("invalid order-book level")
        levels.append(OrderBookLevel(price=Decimal(str(raw[0])), quantity=Decimal(str(raw[1]))))
    return tuple(sorted(levels, key=lambda level: level.price, reverse=reverse))


def _filter(filters: list[object], filter_type: str) -> dict[str, object]:
    for item in filters:
        if isinstance(item, dict) and item.get("filterType") == filter_type:
            return item
    raise KeyError(filter_type)
