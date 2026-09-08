from __future__ import annotations

from tomiris_market_data.models import (
    DataQualityOutcome,
    DataQualityReport,
    MarketDataRequest,
    MarketDataSeries,
)


class MarketDataValidator:
    """Fail-closed validation before any feature computation."""

    def validate(self, series: MarketDataSeries, request: MarketDataRequest) -> DataQualityReport:
        if series.instrument != request.instrument or series.timeframe != request.timeframe:
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("PROVIDER_MISMATCH",),
            )
        if series.as_of != request.as_of:
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("CUTOFF_MISMATCH",),
            )
        bars = series.bars
        if len(bars) < request.minimum_bars:
            return DataQualityReport(
                outcome=DataQualityOutcome.INSUFFICIENT,
                reason_codes=("INSUFFICIENT_HISTORY",),
                accepted_bars=len(bars),
            )
        open_times = [bar.open_time for bar in bars]
        if len(set(open_times)) != len(open_times):
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("DUPLICATE_BAR",),
            )
        if open_times != sorted(open_times):
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("NON_MONOTONIC_TIME",),
            )
        if any(bar.close_time > request.as_of for bar in bars):
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("FUTURE_DATA",),
            )
        if request.closed_only and any(not bar.closed for bar in bars):
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("OPEN_CANDLE",),
            )
        expected_seconds = request.timeframe.seconds
        if any(
            int((current.open_time - previous.open_time).total_seconds()) != expected_seconds
            for previous, current in zip(bars, bars[1:], strict=False)
        ):
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("DATA_GAP",),
            )
        age = (request.as_of - bars[-1].close_time).total_seconds()
        if age < 0:
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("FUTURE_DATA",),
            )
        if age > request.max_data_age_seconds:
            return DataQualityReport(
                outcome=DataQualityOutcome.INVALID,
                reason_codes=("DATA_STALE",),
                accepted_bars=len(bars),
            )
        return DataQualityReport(
            outcome=DataQualityOutcome.VALID,
            accepted_bars=len(bars),
        )
