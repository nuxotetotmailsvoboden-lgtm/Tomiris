from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from typing import Protocol

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import NormalizedMarketEvent
from tomiris_market_data.models import require_utc
from tomiris_market_data.serialization import canonical_json_bytes


class RecentMarketEventStore(Protocol):
    async def append(self, event: NormalizedMarketEvent) -> None: ...

    async def query(
        self,
        *,
        instrument_id: str,
        data_types: frozenset[MarketDataType],
        as_of: datetime,
        limit: int,
    ) -> tuple[NormalizedMarketEvent, ...]: ...

    async def close(self) -> None: ...


class InMemoryRecentMarketEventStore:
    """Bounded recent window; eviction is explicit and never durable truth."""

    def __init__(self, *, max_events: int = 10_000, max_bytes: int = 32_000_000) -> None:
        if max_events < 1 or max_bytes < 1_024:
            raise ValueError("recent event-store bounds are invalid")
        self.max_events = max_events
        self.max_bytes = max_bytes
        self._events: deque[tuple[NormalizedMarketEvent, int]] = deque()
        self._bytes = 0
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def byte_size(self) -> int:
        return self._bytes

    async def append(self, event: NormalizedMarketEvent) -> None:
        encoded_size = len(canonical_json_bytes(event))
        if encoded_size > self.max_bytes:
            raise ValueError("one market event exceeds store byte capacity")
        async with self._lock:
            if self._closed:
                raise RuntimeError("event store is closed")
            while self._events and (
                len(self._events) >= self.max_events or self._bytes + encoded_size > self.max_bytes
            ):
                _old, old_size = self._events.popleft()
                self._bytes -= old_size
            self._events.append((event, encoded_size))
            self._bytes += encoded_size

    async def query(
        self,
        *,
        instrument_id: str,
        data_types: frozenset[MarketDataType],
        as_of: datetime,
        limit: int,
    ) -> tuple[NormalizedMarketEvent, ...]:
        if limit < 1:
            raise ValueError("query limit must be positive")
        require_utc(as_of)
        async with self._lock:
            selected = [
                event
                for event, _size in self._events
                if event.instrument_id == instrument_id
                and event.data_type in data_types
                and event.event_time <= as_of
            ]
        return tuple(selected[-limit:])

    async def close(self) -> None:
        async with self._lock:
            self._events.clear()
            self._bytes = 0
            self._closed = True
