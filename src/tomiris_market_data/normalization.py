from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import (
    AggressorSide,
    FundingRateSnapshot,
    IndexPriceSnapshot,
    LiquidationEvent,
    MarkPriceSnapshot,
    NormalizedMarketEvent,
    OrderBookDelta,
    OrderBookLevel,
    SourceMetadata,
    TradeEvent,
)
from tomiris_market_data.errors import DataValidationError
from tomiris_market_data.identity import CanonicalInstrument

InstrumentResolver = Callable[[str], CanonicalInstrument]


class BinanceFuturesEventNormalizer:
    """Strict Binance USDT-M wire adapter; raw JSON never escapes this boundary."""

    version = "binance-futures-ws.v1"

    def __init__(self, resolver: InstrumentResolver, *, max_message_bytes: int = 1_000_000) -> None:
        if max_message_bytes < 1_024 or max_message_bytes > 10_000_000:
            raise ValueError("stream message bound is invalid")
        self.resolver = resolver
        self.max_message_bytes = max_message_bytes

    def normalize(
        self, raw: bytes | str, *, received_at: datetime, processed_at: datetime
    ) -> tuple[NormalizedMarketEvent, ...]:
        encoded = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        if len(encoded) > self.max_message_bytes:
            raise DataValidationError("STREAM_MESSAGE_TOO_LARGE", "stream message exceeds bound")
        try:
            decoded: object = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataValidationError(
                "MALFORMED_PAYLOAD", "stream message is invalid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise DataValidationError("MALFORMED_PAYLOAD", "stream payload must be an object")
        payload: object = decoded.get("data", decoded)
        if not isinstance(payload, dict):
            raise DataValidationError("MALFORMED_PAYLOAD", "combined stream data must be an object")
        try:
            event_type = str(payload["e"])
            raw_order = payload.get("o")
            symbol_value = payload.get("s")
            if symbol_value is None and event_type == "forceOrder" and isinstance(raw_order, dict):
                symbol_value = raw_order.get("s")
            if symbol_value is None:
                raise KeyError("s")
            symbol = str(symbol_value)
            instrument = self.resolver(symbol)
            if event_type == "markPriceUpdate":
                exchange_value = payload["E"]
            elif event_type == "forceOrder" and isinstance(raw_order, dict):
                exchange_value = raw_order.get("T", payload["E"])
            else:
                exchange_value = payload.get("T", payload["E"])
            exchange_at = _timestamp(exchange_value)
            source = SourceMetadata(
                endpoint="wss://fstream.binance.com",
                stream=str(decoded.get("stream", event_type)),
                source_event_type=event_type,
                normalizer_version=self.version,
                provenance=f"binance-public-ws:{event_type}",
            )
            if event_type in {"trade", "aggTrade"}:
                return (
                    self._trade(
                        payload,
                        instrument,
                        event_type,
                        exchange_at,
                        received_at,
                        processed_at,
                        source,
                    ),
                )
            if event_type == "depthUpdate":
                return (
                    self._depth(
                        payload,
                        instrument,
                        exchange_at,
                        received_at,
                        processed_at,
                        source,
                    ),
                )
            if event_type == "markPriceUpdate":
                return self._premium(
                    payload,
                    instrument,
                    exchange_at,
                    received_at,
                    processed_at,
                    source,
                )
            if event_type == "forceOrder":
                return (
                    self._liquidation(
                        payload,
                        instrument,
                        exchange_at,
                        received_at,
                        processed_at,
                        source,
                    ),
                )
        except DataValidationError:
            raise
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise DataValidationError(
                "MALFORMED_PAYLOAD", "stream payload failed schema validation"
            ) from exc
        raise DataValidationError("UNSUPPORTED_EVENT", f"unsupported stream event {event_type}")

    def _trade(
        self,
        data: dict[object, object],
        instrument: CanonicalInstrument,
        event_type: str,
        exchange_at: datetime,
        received_at: datetime,
        processed_at: datetime,
        source: SourceMetadata,
    ) -> NormalizedMarketEvent:
        trade_id = str(data["a"] if event_type == "aggTrade" else data["t"])
        buyer_is_maker = data.get("m")
        aggressor = AggressorSide.UNKNOWN
        if isinstance(buyer_is_maker, bool):
            aggressor = AggressorSide.SELL if buyer_is_maker else AggressorSide.BUY
        observation = TradeEvent(
            provider="binance-futures-public",
            instrument=instrument,
            exchange_timestamp=exchange_at,
            received_at=received_at,
            source=source,
            trade_id=trade_id,
            price=Decimal(str(data["p"])),
            quantity=Decimal(str(data["q"])),
            aggressor=aggressor,
            provider_sequence=int(trade_id),
        )
        data_type = (
            MarketDataType.AGGREGATE_TRADES if event_type == "aggTrade" else MarketDataType.TRADES
        )
        return _envelope(
            event_id=f"BINANCE:{event_type}:{instrument.symbol}:{trade_id}",
            data_type=data_type,
            instrument=instrument,
            event_time=exchange_at,
            received_at=received_at,
            processed_at=processed_at,
            sequence=int(trade_id),
            payload=observation,
            source=source,
        )

    def _depth(
        self,
        data: dict[object, object],
        instrument: CanonicalInstrument,
        exchange_at: datetime,
        received_at: datetime,
        processed_at: datetime,
        source: SourceMetadata,
    ) -> NormalizedMarketEvent:
        first_id = _as_int(data["U"])
        final_id = _as_int(data["u"])
        observation = OrderBookDelta(
            provider="binance-futures-public",
            instrument=instrument,
            exchange_timestamp=exchange_at,
            received_at=received_at,
            source=source,
            first_update_id=first_id,
            final_update_id=final_id,
            previous_final_update_id=_as_int(data["pu"]) if data.get("pu") is not None else None,
            bids=_levels(data["b"]),
            asks=_levels(data["a"]),
        )
        return _envelope(
            event_id=f"BINANCE:depth:{instrument.symbol}:{first_id}:{final_id}",
            data_type=MarketDataType.ORDER_BOOK_DELTA,
            instrument=instrument,
            event_time=exchange_at,
            received_at=received_at,
            processed_at=processed_at,
            sequence=final_id,
            payload=observation,
            source=source,
        )

    def _premium(
        self,
        data: dict[object, object],
        instrument: CanonicalInstrument,
        exchange_at: datetime,
        received_at: datetime,
        processed_at: datetime,
        source: SourceMetadata,
    ) -> tuple[NormalizedMarketEvent, ...]:
        common = {
            "provider": "binance-futures-public",
            "instrument": instrument,
            "exchange_timestamp": exchange_at,
            "received_at": received_at,
            "source": source,
        }
        observations = (
            (
                MarketDataType.MARK_PRICE,
                MarkPriceSnapshot(mark_price=Decimal(str(data["p"])), **common),
            ),
            (
                MarketDataType.INDEX_PRICE,
                IndexPriceSnapshot(index_price=Decimal(str(data["i"])), **common),
            ),
            (
                MarketDataType.FUNDING_RATE,
                FundingRateSnapshot(
                    rate=Decimal(str(data["r"])),
                    next_funding_at=_timestamp(data["T"]),
                    **common,
                ),
            ),
        )
        return tuple(
            _envelope(
                event_id=(
                    f"BINANCE:{data_type.value}:{instrument.symbol}:"
                    f"{int(exchange_at.timestamp() * 1_000)}"
                ),
                data_type=data_type,
                instrument=instrument,
                event_time=exchange_at,
                received_at=received_at,
                processed_at=processed_at,
                sequence=None,
                payload=observation,
                source=source,
            )
            for data_type, observation in observations
        )

    def _liquidation(
        self,
        data: dict[object, object],
        instrument: CanonicalInstrument,
        exchange_at: datetime,
        received_at: datetime,
        processed_at: datetime,
        source: SourceMetadata,
    ) -> NormalizedMarketEvent:
        order = data["o"]
        if not isinstance(order, dict):
            raise TypeError("force order body must be an object")
        forced_side = str(order.get("S", ""))
        side = (
            AggressorSide.BUY
            if forced_side == "BUY"
            else AggressorSide.SELL
            if forced_side == "SELL"
            else AggressorSide.UNKNOWN
        )
        provider_id = f"{order.get('T', data.get('E'))}:{forced_side}:{order.get('q')}"
        observation = LiquidationEvent(
            provider="binance-futures-public",
            instrument=instrument,
            exchange_timestamp=exchange_at,
            received_at=received_at,
            source=source,
            event_id=provider_id,
            side=side,
            price=Decimal(str(order["p"])),
            quantity=Decimal(str(order["q"])),
            average_price=Decimal(str(order["ap"])) if order.get("ap") is not None else None,
            provider_semantics="Binance forceOrder order side; causal actor is not inferred",
        )
        return _envelope(
            event_id=f"BINANCE:forceOrder:{instrument.symbol}:{provider_id}",
            data_type=MarketDataType.LIQUIDATION,
            instrument=instrument,
            event_time=exchange_at,
            received_at=received_at,
            processed_at=processed_at,
            sequence=None,
            payload=observation,
            source=source,
        )


def _timestamp(value: object) -> datetime:
    return datetime.fromtimestamp(_as_int(value) / 1_000, tz=UTC)


def _as_int(value: object) -> int:
    return int(str(value))


def _levels(value: object) -> tuple[OrderBookLevel, ...]:
    if not isinstance(value, list) or len(value) > 5_000:
        raise TypeError("invalid bounded depth levels")
    result: list[OrderBookLevel] = []
    for raw in value:
        if not isinstance(raw, list) or len(raw) < 2:
            raise TypeError("invalid depth level")
        result.append(OrderBookLevel(price=Decimal(str(raw[0])), quantity=Decimal(str(raw[1]))))
    return tuple(result)


def _envelope(
    *,
    event_id: str,
    data_type: MarketDataType,
    instrument: CanonicalInstrument,
    event_time: datetime,
    received_at: datetime,
    processed_at: datetime,
    sequence: int | None,
    payload: TradeEvent
    | OrderBookDelta
    | MarkPriceSnapshot
    | IndexPriceSnapshot
    | FundingRateSnapshot
    | LiquidationEvent,
    source: SourceMetadata,
) -> NormalizedMarketEvent:
    return NormalizedMarketEvent(
        event_id=event_id,
        provider="binance-futures-public",
        venue="BINANCE",
        instrument=instrument,
        data_type=data_type,
        event_time=event_time,
        exchange_time=event_time,
        received_at=received_at,
        processed_at=processed_at,
        sequence=sequence,
        payload=payload,
        source=source,
    )
