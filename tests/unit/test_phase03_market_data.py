from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from tests.phase03_support import make_series
from tests.support import NOW

from tomiris_market_data.models import (
    DataQualityOutcome,
    MarketDataRequest,
    MarketDataSeries,
    OHLCVBar,
    Timeframe,
)
from tomiris_market_data.validation import MarketDataValidator


def request(**changes: object) -> MarketDataRequest:
    values: dict[str, object] = {
        "instrument": "ETHUSDT",
        "timeframe": Timeframe.H1,
        "minimum_bars": 20,
        "as_of": NOW,
        "max_data_age_seconds": 7_200,
    }
    values.update(changes)
    return MarketDataRequest.model_validate(values)


def test_valid_ohlcv_and_quality_gate() -> None:
    series = make_series(count=20, as_of=NOW)
    report = MarketDataValidator().validate(series, request())
    assert report.outcome == DataQualityOutcome.VALID
    assert report.accepted_bars == 20


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volume", Decimal("-1")),
        ("close", Decimal("NaN")),
        ("high", Decimal("1")),
        ("low", Decimal("1000")),
    ],
)
def test_ohlcv_rejects_invalid_numeric_invariants(field: str, value: Decimal) -> None:
    valid = make_series(count=2, as_of=NOW).bars[0].model_dump()
    valid[field] = value
    with pytest.raises(ValidationError):
        OHLCVBar.model_validate(valid)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("duplicate", "DUPLICATE_BAR"),
        ("gap", "DATA_GAP"),
        ("future", "FUTURE_DATA"),
        ("open", "OPEN_CANDLE"),
    ],
)
def test_quality_gate_rejects_time_integrity_failures(mutation: str, reason: str) -> None:
    original = make_series(count=21, as_of=NOW)
    bars = list(original.bars)
    minimum = 20
    if mutation == "duplicate":
        bars[-1] = bars[-2]
    elif mutation == "gap":
        del bars[10]
    elif mutation == "future":
        bars[-1] = bars[-1].model_copy(update={"close_time": NOW + timedelta(seconds=1)})
    else:
        bars[-1] = bars[-1].model_copy(update={"closed": False})
    series = MarketDataSeries(
        provider=original.provider,
        instrument=original.instrument,
        timeframe=original.timeframe,
        as_of=original.as_of,
        bars=tuple(bars),
    )
    report = MarketDataValidator().validate(series, request(minimum_bars=minimum))
    assert report.outcome == DataQualityOutcome.INVALID
    assert report.reason_codes == (reason,)


def test_quality_gate_distinguishes_stale_insufficient_and_wrong_instrument() -> None:
    series = make_series(count=20, as_of=NOW)
    stale_cutoff = NOW + timedelta(hours=3)
    stale = MarketDataValidator().validate(
        series.model_copy(update={"as_of": stale_cutoff}),
        request(as_of=stale_cutoff, max_data_age_seconds=60),
    )
    insufficient = MarketDataValidator().validate(series, request(minimum_bars=21))
    wrong = MarketDataValidator().validate(series, request(instrument="SOLUSDT"))
    wrong_cutoff = MarketDataValidator().validate(
        series.model_copy(update={"as_of": NOW - timedelta(seconds=1)}),
        request(),
    )
    assert stale.reason_codes == ("DATA_STALE",)
    assert insufficient.outcome == DataQualityOutcome.INSUFFICIENT
    assert wrong.reason_codes == ("PROVIDER_MISMATCH",)
    assert wrong_cutoff.reason_codes == ("CUTOFF_MISMATCH",)


def test_series_rejects_mixed_asset_and_naive_time() -> None:
    eth = make_series(count=2, as_of=NOW)
    sol_bar = make_series(instrument="SOLUSDT", count=2, as_of=NOW).bars[0]
    with pytest.raises(ValidationError):
        MarketDataSeries(
            provider="fixture",
            instrument="ETHUSDT",
            timeframe=Timeframe.H1,
            as_of=NOW,
            bars=(eth.bars[0], sol_bar),
        )
    with pytest.raises(ValidationError):
        request(as_of=NOW.replace(tzinfo=None))
