from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from tomiris_market_data.models import MarketDataSeries


class MarketDataCache(Protocol):
    async def get(self, key: str, now: datetime) -> MarketDataSeries | None: ...

    async def put(
        self, key: str, value: MarketDataSeries, now: datetime, ttl_seconds: int
    ) -> None: ...


@dataclass(frozen=True)
class _CacheEntry:
    value: MarketDataSeries
    expires_at: datetime


class InMemoryMarketDataCache:
    """Bounded process-local cache; no cross-process correctness is assumed."""

    def __init__(self, max_entries: int = 256) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str, now: datetime) -> MarketDataSeries | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._entries[key]
                return None
            return entry.value

    async def put(self, key: str, value: MarketDataSeries, now: datetime, ttl_seconds: int) -> None:
        async with self._lock:
            if key not in self._entries and len(self._entries) >= self.max_entries:
                oldest = next(iter(self._entries))
                del self._entries[oldest]
            self._entries[key] = _CacheEntry(value, now + timedelta(seconds=ttl_seconds))
