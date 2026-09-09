from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from tomiris_market_data.buffer import BoundedOrderBookDeltaBuffer, BufferPolicy
from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import (
    OrderBookDelta,
    OrderBookLevel,
    OrderBookSnapshot,
)
from tomiris_market_data.errors import BufferOverflowError
from tomiris_market_data.identity import CanonicalInstrument
from tomiris_market_data.plane_metrics import MarketDataPlaneMetrics


class OrderBookSyncState(StrEnum):
    EMPTY = "EMPTY"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    SYNCED = "SYNCED"
    OUT_OF_SYNC = "OUT_OF_SYNC"
    RECONNECTING = "RECONNECTING"
    STOPPED = "STOPPED"


class DeltaApplyResult(StrEnum):
    APPLIED = "APPLIED"
    DUPLICATE_OR_OLD = "DUPLICATE_OR_OLD"
    BUFFERED = "BUFFERED"
    GAP = "GAP"
    BUFFER_OVERFLOW = "BUFFER_OVERFLOW"


class OrderBookView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument: CanonicalInstrument
    state: OrderBookSyncState
    last_update_id: int | None = Field(default=None, ge=0)
    bids: tuple[OrderBookLevel, ...] = ()
    asks: tuple[OrderBookLevel, ...] = ()
    safe_for_analysis: bool = False
    reason_code: str | None = None


class OrderBookSynchronizer:
    """Atomic snapshot+delta book with fail-closed Binance-compatible sequencing."""

    def __init__(
        self,
        instrument: CanonicalInstrument,
        provider: str,
        *,
        max_depth: int = 1_000,
        buffer_policy: BufferPolicy | None = None,
        metrics: MarketDataPlaneMetrics | None = None,
    ) -> None:
        if max_depth < 1 or max_depth > 5_000:
            raise ValueError("order-book depth bound is invalid")
        self.instrument = instrument
        self.provider = provider
        self.max_depth = max_depth
        self.buffer = BoundedOrderBookDeltaBuffer(buffer_policy)
        self.metrics = metrics or MarketDataPlaneMetrics()
        self.state = OrderBookSyncState.EMPTY
        self.last_update_id: int | None = None
        self._bids: dict[Decimal, Decimal] = {}
        self._asks: dict[Decimal, Decimal] = {}
        self._reason: str | None = None
        self._resyncing = False
        self._lock = asyncio.Lock()

    async def buffer_delta(self, delta: OrderBookDelta) -> DeltaApplyResult:
        async with self._lock:
            self._validate_identity(delta)
            try:
                self.buffer.append(delta)
            except BufferOverflowError:
                self._mark_out_of_sync("BUFFER_OVERFLOW")
                return DeltaApplyResult.BUFFER_OVERFLOW
            if self.state in {OrderBookSyncState.EMPTY, OrderBookSyncState.RECONNECTING}:
                self.state = OrderBookSyncState.BOOTSTRAPPING
            return DeltaApplyResult.BUFFERED

    async def bootstrap(self, snapshot: OrderBookSnapshot) -> OrderBookView:
        async with self._lock:
            self._validate_identity(snapshot)
            self.state = OrderBookSyncState.BOOTSTRAPPING
            self._reason = None
            self._bids = {level.price: level.quantity for level in snapshot.bids}
            self._asks = {level.price: level.quantity for level in snapshot.asks}
            self.last_update_id = snapshot.last_update_id
            pending = [
                delta
                for delta in self.buffer.items
                if delta.final_update_id > snapshot.last_update_id
            ]
            self.buffer.clear()
            for delta in pending:
                outcome = self._apply_locked(delta)
                if outcome == DeltaApplyResult.GAP:
                    return self._view_locked()
            if self._crossed_or_empty():
                self._mark_out_of_sync("ORDER_BOOK_INVARIANT_FAILED")
            else:
                self.state = OrderBookSyncState.SYNCED
                self._reason = None
                if self._resyncing:
                    self.metrics.increment(
                        "market_resync_total",
                        self.provider,
                        self.instrument.market_type,
                        MarketDataType.ORDER_BOOK_DELTA,
                    )
                self._resyncing = False
            return self._view_locked()

    async def apply_delta(self, delta: OrderBookDelta) -> DeltaApplyResult:
        async with self._lock:
            self._validate_identity(delta)
            if self.state != OrderBookSyncState.SYNCED:
                try:
                    self.buffer.append(delta)
                except BufferOverflowError:
                    self._mark_out_of_sync("BUFFER_OVERFLOW")
                    return DeltaApplyResult.BUFFER_OVERFLOW
                return DeltaApplyResult.BUFFERED
            return self._apply_locked(delta)

    async def mark_disconnected(self) -> None:
        async with self._lock:
            self.state = OrderBookSyncState.RECONNECTING
            self._reason = "STREAM_DISCONNECTED"
            self._resyncing = True
            self.buffer.clear()

    async def recover(
        self, fetch_snapshot: Callable[[], Awaitable[OrderBookSnapshot]]
    ) -> OrderBookView:
        async with self._lock:
            if self.state == OrderBookSyncState.STOPPED:
                raise RuntimeError("stopped order book cannot recover")
            self.state = OrderBookSyncState.BOOTSTRAPPING
            self._reason = "RESYNC_IN_PROGRESS"
        snapshot = await fetch_snapshot()
        return await self.bootstrap(snapshot)

    async def stop(self) -> None:
        async with self._lock:
            self.state = OrderBookSyncState.STOPPED
            self._reason = "STREAM_STOPPED"
            self.buffer.clear()

    async def read(self) -> OrderBookView:
        async with self._lock:
            return self._view_locked()

    def _apply_locked(self, delta: OrderBookDelta) -> DeltaApplyResult:
        if self.last_update_id is None:
            self._mark_out_of_sync("SNAPSHOT_REQUIRED")
            return DeltaApplyResult.GAP
        if delta.final_update_id <= self.last_update_id:
            return DeltaApplyResult.DUPLICATE_OR_OLD
        expected = self.last_update_id + 1
        bridges = delta.first_update_id <= expected <= delta.final_update_id
        previous_matches = (
            delta.previous_final_update_id is None
            or delta.previous_final_update_id == self.last_update_id
        )
        if not bridges or not previous_matches:
            self._mark_out_of_sync("SEQUENCE_GAP")
            self.metrics.increment(
                "market_sequence_gaps_total",
                self.provider,
                self.instrument.market_type,
                MarketDataType.ORDER_BOOK_DELTA,
            )
            return DeltaApplyResult.GAP
        self._apply_levels(self._bids, delta.bids)
        self._apply_levels(self._asks, delta.asks)
        self.last_update_id = delta.final_update_id
        if self._crossed_or_empty():
            self._mark_out_of_sync("ORDER_BOOK_INVARIANT_FAILED")
            return DeltaApplyResult.GAP
        return DeltaApplyResult.APPLIED

    @staticmethod
    def _apply_levels(book: dict[Decimal, Decimal], levels: tuple[OrderBookLevel, ...]) -> None:
        for level in levels:
            if level.quantity == 0:
                book.pop(level.price, None)
            else:
                book[level.price] = level.quantity

    def _crossed_or_empty(self) -> bool:
        return not self._bids or not self._asks or max(self._bids) >= min(self._asks)

    def _mark_out_of_sync(self, reason: str) -> None:
        self.state = OrderBookSyncState.OUT_OF_SYNC
        self._reason = reason
        self._resyncing = True

    def _validate_identity(self, observation: OrderBookSnapshot | OrderBookDelta) -> None:
        if observation.instrument != self.instrument or observation.provider != self.provider:
            raise ValueError("order-book instrument/provider mismatch")

    def _view_locked(self) -> OrderBookView:
        bids = tuple(
            OrderBookLevel(price=price, quantity=self._bids[price])
            for price in sorted(self._bids, reverse=True)[: self.max_depth]
        )
        asks = tuple(
            OrderBookLevel(price=price, quantity=self._asks[price])
            for price in sorted(self._asks)[: self.max_depth]
        )
        return OrderBookView(
            instrument=self.instrument,
            state=self.state,
            last_update_id=self.last_update_id,
            bids=bids,
            asks=asks,
            safe_for_analysis=self.state == OrderBookSyncState.SYNCED,
            reason_code=self._reason,
        )
