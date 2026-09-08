from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from tomiris_agent_roles.builtin import create_builtin_role_registry
from tomiris_agent_roles.definitions import AgentDefinitionLoader
from tomiris_agent_roles.models import AgentDefinition
from tomiris_market_data.errors import ProviderError
from tomiris_market_data.models import (
    MarketDataBundle,
    MarketDataRequest,
    MarketDataSeries,
    MarketSummary,
    OHLCVBar,
    ProviderMetadata,
    TickerSnapshot,
    Timeframe,
)


def load_pilot_definitions() -> dict[str, AgentDefinition]:
    return AgentDefinitionLoader(create_builtin_role_registry()).load_directory(
        Path("agents/definitions")
    )


def make_series(
    *,
    instrument: str = "ETHUSDT",
    timeframe: Timeframe = Timeframe.H1,
    as_of: datetime = datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
    count: int = 220,
    pattern: str = "up",
    provider: str = "fixture",
) -> MarketDataSeries:
    delta = timedelta(seconds=timeframe.seconds)
    first_open = as_of - (delta * count)
    previous_close = 100.0
    bars: list[OHLCVBar] = []
    for index in range(count):
        if pattern == "up":
            close = 100.0 + index * 0.35
        elif pattern == "down":
            close = 200.0 - index * 0.35
        elif pattern == "range":
            close = 100.0 + math.sin(index / 3.0) * 0.6
        elif pattern == "high_volatility":
            close = 100.0 + ((-1.0) ** index) * (4.0 + (index % 5))
        else:
            raise ValueError(f"unknown fixture pattern: {pattern}")
        open_value = previous_close
        high = max(open_value, close) + (5.0 if pattern == "high_volatility" else 0.25)
        low = min(open_value, close) - (5.0 if pattern == "high_volatility" else 0.25)
        open_time = first_open + delta * index
        close_time = open_time + delta
        bars.append(
            OHLCVBar(
                provider=provider,
                instrument=instrument,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open=Decimal(str(open_value)),
                high=Decimal(str(high)),
                low=Decimal(str(low)),
                close=Decimal(str(close)),
                volume=Decimal(str(1_000 + index * (4 if pattern == "up" else 1))),
                received_at=as_of,
                source_timestamp=close_time,
                freshness_seconds=max(0.0, (as_of - close_time).total_seconds()),
                provenance="fixture:generated:v1",
                closed=True,
            )
        )
        previous_close = close
    return MarketDataSeries(
        provider=provider,
        instrument=instrument,
        timeframe=timeframe,
        as_of=as_of,
        bars=tuple(bars),
    )


def make_bundle(
    snapshot_id: UUID,
    *,
    instrument: str,
    as_of: datetime,
    pattern_by_timeframe: dict[Timeframe, str] | None = None,
) -> MarketDataBundle:
    patterns = pattern_by_timeframe or {timeframe: "up" for timeframe in Timeframe}
    series = tuple(
        make_series(
            instrument=instrument,
            timeframe=timeframe,
            as_of=as_of,
            pattern=pattern,
        )
        for timeframe, pattern in patterns.items()
    )
    return MarketDataBundle(
        snapshot_id=snapshot_id,
        as_of=as_of,
        series=series,
        providers=(
            ProviderMetadata(
                provider="fixture",
                received_at=as_of,
                source_timestamp=max(item.bars[-1].close_time for item in series),
                freshness_seconds=0,
                provenance="fixture:generated:v1",
            ),
        ),
    )


class StaticMarketDataProvider:
    name = "fixture"

    def __init__(
        self,
        patterns: dict[str, str] | None = None,
        *,
        failure_code: str | None = None,
    ) -> None:
        self.patterns = patterns or {}
        self.failure_code = failure_code
        self.calls = 0

    async def get_ohlcv(self, request: MarketDataRequest) -> MarketDataSeries:
        self.calls += 1
        if self.failure_code:
            raise ProviderError(self.failure_code, "fixture provider failure")
        return make_series(
            instrument=request.instrument,
            timeframe=request.timeframe,
            as_of=request.as_of,
            count=request.minimum_bars,
            pattern=self.patterns.get(request.instrument, "up"),
        )

    async def get_ticker(self, instrument: str) -> TickerSnapshot:
        now = datetime.now(UTC)
        return TickerSnapshot(
            provider=self.name,
            instrument=instrument,
            price=Decimal("100"),
            observed_at=now,
            received_at=now,
        )

    async def get_market_summary(self, instrument: str) -> MarketSummary:
        now = datetime.now(UTC)
        return MarketSummary(
            provider=self.name,
            instrument=instrument,
            price_change_percent=Decimal("1"),
            quote_volume=Decimal("1000000"),
            observed_at=now,
            received_at=now,
        )
