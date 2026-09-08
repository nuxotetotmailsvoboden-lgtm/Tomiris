from __future__ import annotations

from typing import Protocol

from tomiris_market_data.models import (
    MarketDataRequest,
    MarketDataSeries,
    MarketSummary,
    TickerSnapshot,
)


class MarketDataProvider(Protocol):
    name: str

    async def get_ohlcv(self, request: MarketDataRequest) -> MarketDataSeries: ...

    async def get_ticker(self, instrument: str) -> TickerSnapshot: ...

    async def get_market_summary(self, instrument: str) -> MarketSummary: ...
