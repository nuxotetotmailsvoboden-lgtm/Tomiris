from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from tests.phase03_support import make_series
from tests.support import NOW

from tomiris_features.indicators import ATRFeature, EMAFeature, MACDFeature, RSIFeature
from tomiris_features.pipeline import FeaturePipelineConfig, TechnicalFeaturePipeline
from tomiris_market_data.models import MarketDataSeries, OHLCVBar, Timeframe


def series_from_closes(values: list[float]) -> MarketDataSeries:
    start = NOW - timedelta(hours=len(values))
    bars = []
    previous = values[0]
    for index, close in enumerate(values):
        open_time = start + timedelta(hours=index)
        margin = min(1.0, min(previous, close) / 2)
        bars.append(
            OHLCVBar(
                provider="fixture",
                instrument="ETHUSDT",
                timeframe=Timeframe.H1,
                open_time=open_time,
                close_time=open_time + timedelta(hours=1),
                open=Decimal(str(previous)),
                high=Decimal(str(max(previous, close) + margin)),
                low=Decimal(str(min(previous, close) - margin)),
                close=Decimal(str(close)),
                volume=Decimal("100"),
                received_at=NOW,
                source_timestamp=open_time + timedelta(hours=1),
                freshness_seconds=0,
                provenance="fixture:independent-values",
            )
        )
        previous = close
    return MarketDataSeries(
        provider="fixture",
        instrument="ETHUSDT",
        timeframe=Timeframe.H1,
        as_of=NOW,
        bars=tuple(bars),
    )


def test_ema_matches_independent_known_value() -> None:
    result = EMAFeature(3).compute(series_from_closes([1, 2, 3]))
    assert result.valid
    assert result.values["ema"] == pytest.approx(2.25, abs=1e-12)


def test_rsi_macd_atr_constant_series_expected_values() -> None:
    series = series_from_closes([100] * 40)
    rsi = RSIFeature(14).compute(series)
    macd = MACDFeature(12, 26, 9).compute(series)
    atr = ATRFeature(14).compute(series)
    assert rsi.values["rsi"] == 50
    assert macd.values == pytest.approx({"macd": 0, "signal": 0, "histogram": 0})
    assert atr.values["atr"] == pytest.approx(2.0)
    assert atr.values["atr_percent"] == pytest.approx(0.02)


@pytest.mark.parametrize("pattern", ["up", "down", "range", "high_volatility"])
def test_pipeline_is_deterministic_finite_and_bounded(pattern: str) -> None:
    series = make_series(count=220, as_of=NOW, pattern=pattern)
    pipeline = TechnicalFeaturePipeline(FeaturePipelineConfig())
    first = pipeline.compute(series)
    second = pipeline.compute(series)
    assert first == second
    assert all(item.valid for item in first)
    rsi = next(item for item in first if item.feature_name == "rsi")
    atr = next(item for item in first if item.feature_name == "atr")
    assert 0 <= rsi.values["rsi"] <= 100
    assert atr.values["atr"] >= 0


def test_features_report_insufficient_history_instead_of_nan() -> None:
    series = make_series(count=5, as_of=NOW)
    results = TechnicalFeaturePipeline(FeaturePipelineConfig()).compute(series)
    assert any(not result.valid for result in results)
    assert all(
        result.reason_code == "INSUFFICIENT_HISTORY" for result in results if not result.valid
    )


def test_cutoff_excludes_future_data_before_features() -> None:
    series = make_series(count=50, as_of=NOW)
    future = series.bars[-1].model_copy(
        update={
            "open_time": NOW + timedelta(hours=1),
            "close_time": NOW + timedelta(hours=2),
        }
    )
    contaminated = MarketDataSeries(
        provider=series.provider,
        instrument=series.instrument,
        timeframe=series.timeframe,
        as_of=NOW,
        bars=(*series.bars, future),
    )
    from tomiris_market_data.models import MarketDataRequest
    from tomiris_market_data.validation import MarketDataValidator

    report = MarketDataValidator().validate(
        contaminated,
        MarketDataRequest(
            instrument="ETHUSDT",
            timeframe=Timeframe.H1,
            minimum_bars=50,
            as_of=NOW,
            max_data_age_seconds=7_200,
        ),
    )
    assert report.reason_codes == ("FUTURE_DATA",)
