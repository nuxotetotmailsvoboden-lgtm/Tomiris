from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tomiris_market_data.errors import DataValidationError
from tomiris_market_data.models import (
    DataQualityOutcome,
    MarketDataBundle,
    MarketDataRequest,
    MarketDataSeries,
    ProviderMetadata,
)
from tomiris_market_data.provider import MarketDataProvider
from tomiris_market_data.validation import MarketDataValidator


@dataclass(frozen=True)
class CollectedMarketData:
    bundle: MarketDataBundle
    quality_by_request: dict[str, DataQualityOutcome]


class MarketDataCollector:
    def __init__(
        self,
        provider: MarketDataProvider,
        validator: MarketDataValidator | None = None,
        *,
        max_concurrency: int = 4,
    ) -> None:
        self.provider = provider
        self.validator = validator or MarketDataValidator()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def collect(
        self,
        snapshot_id: UUID,
        as_of: datetime,
        requests: tuple[MarketDataRequest, ...],
    ) -> CollectedMarketData:
        async def fetch(
            request: MarketDataRequest,
        ) -> tuple[MarketDataRequest, MarketDataSeries]:
            async with self._semaphore:
                return request, await self.provider.get_ohlcv(request)

        fetched = await asyncio.gather(*(fetch(request) for request in requests))
        series = []
        quality: dict[str, DataQualityOutcome] = {}
        providers: dict[tuple[str, datetime], ProviderMetadata] = {}
        for request, raw_series in fetched:
            report = self.validator.validate(raw_series, request)
            key = f"{request.instrument}:{request.timeframe.value}"
            quality[key] = report.outcome
            if report.outcome not in {DataQualityOutcome.VALID, DataQualityOutcome.DEGRADED}:
                reason = report.reason_codes[0] if report.reason_codes else "INVALID_MARKET_DATA"
                raise DataValidationError(reason, f"market data failed quality gate for {key}")
            typed_series = raw_series
            series.append(typed_series)
            last_bar = typed_series.bars[-1]
            providers[(typed_series.provider, last_bar.source_timestamp)] = ProviderMetadata(
                provider=typed_series.provider,
                received_at=last_bar.received_at,
                source_timestamp=last_bar.source_timestamp,
                freshness_seconds=last_bar.freshness_seconds,
                provenance=last_bar.provenance,
            )
        return CollectedMarketData(
            bundle=MarketDataBundle(
                snapshot_id=snapshot_id,
                as_of=as_of,
                series=tuple(series),
                providers=tuple(providers.values()),
            ),
            quality_by_request=quality,
        )
