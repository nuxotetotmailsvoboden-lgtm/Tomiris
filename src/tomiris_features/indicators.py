from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from dataclasses import dataclass

from tomiris_features.models import FeatureResult
from tomiris_market_data.models import MarketDataSeries


def _invalid(
    name: str,
    version: str,
    series: MarketDataSeries,
    parameters: Mapping[str, int | float | str],
    reason: str = "INSUFFICIENT_HISTORY",
) -> FeatureResult:
    return FeatureResult(
        feature_name=name,
        feature_version=version,
        parameters=dict(parameters),
        values={},
        timeframe=series.timeframe,
        as_of=series.bars[-1].close_time,
        valid=False,
        reason_code=reason,
    )


def _ema_values(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    multiplier = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


@dataclass(frozen=True)
class EMAFeature:
    period: int
    feature_name: str = "ema"
    feature_version: str = "ema.v1"

    def compute(self, series: MarketDataSeries) -> FeatureResult:
        parameters = {"period": self.period}
        if self.period < 2 or len(series.bars) < self.period:
            return _invalid(self.feature_name, self.feature_version, series, parameters)
        values = _ema_values([float(bar.close) for bar in series.bars], self.period)
        return FeatureResult(
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            parameters=parameters,
            values={"ema": values[-1]},
            timeframe=series.timeframe,
            as_of=series.bars[-1].close_time,
            valid=True,
        )


@dataclass(frozen=True)
class RSIFeature:
    period: int
    feature_name: str = "rsi"
    feature_version: str = "rsi.wilder.v1"

    def compute(self, series: MarketDataSeries) -> FeatureResult:
        parameters = {"period": self.period}
        closes = [float(bar.close) for bar in series.bars]
        if self.period < 2 or len(closes) <= self.period:
            return _invalid(self.feature_name, self.feature_version, series, parameters)
        changes = [
            current - previous for previous, current in zip(closes, closes[1:], strict=False)
        ]
        gains = [max(change, 0.0) for change in changes]
        losses = [max(-change, 0.0) for change in changes]
        avg_gain = sum(gains[: self.period]) / self.period
        avg_loss = sum(losses[: self.period]) / self.period
        for gain, loss in zip(gains[self.period :], losses[self.period :], strict=False):
            avg_gain = ((avg_gain * (self.period - 1)) + gain) / self.period
            avg_loss = ((avg_loss * (self.period - 1)) + loss) / self.period
        if avg_loss == 0 and avg_gain == 0:
            rsi = 50.0
        elif avg_loss == 0:
            rsi = 100.0
        else:
            rsi = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
        return FeatureResult(
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            parameters=parameters,
            values={"rsi": min(100.0, max(0.0, rsi))},
            timeframe=series.timeframe,
            as_of=series.bars[-1].close_time,
            valid=True,
        )


@dataclass(frozen=True)
class MACDFeature:
    fast: int
    slow: int
    signal: int
    feature_name: str = "macd"
    feature_version: str = "macd.v1"

    def compute(self, series: MarketDataSeries) -> FeatureResult:
        parameters = {"fast": self.fast, "slow": self.slow, "signal": self.signal}
        closes = [float(bar.close) for bar in series.bars]
        if (
            self.fast < 2
            or self.slow <= self.fast
            or self.signal < 2
            or len(closes) < self.slow + self.signal
        ):
            return _invalid(self.feature_name, self.feature_version, series, parameters)
        fast_values = _ema_values(closes, self.fast)
        slow_values = _ema_values(closes, self.slow)
        macd_values = [
            fast_value - slow_value
            for fast_value, slow_value in zip(fast_values, slow_values, strict=True)
        ]
        signal_values = _ema_values(macd_values, self.signal)
        histogram = macd_values[-1] - signal_values[-1]
        return FeatureResult(
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            parameters=parameters,
            values={"macd": macd_values[-1], "signal": signal_values[-1], "histogram": histogram},
            timeframe=series.timeframe,
            as_of=series.bars[-1].close_time,
            valid=True,
        )


@dataclass(frozen=True)
class ATRFeature:
    period: int
    feature_name: str = "atr"
    feature_version: str = "atr.wilder.v1"

    def compute(self, series: MarketDataSeries) -> FeatureResult:
        parameters = {"period": self.period}
        if self.period < 2 or len(series.bars) <= self.period:
            return _invalid(self.feature_name, self.feature_version, series, parameters)
        ranges: list[float] = []
        previous_close: float | None = None
        for bar in series.bars:
            high = float(bar.high)
            low = float(bar.low)
            true_range = high - low
            if previous_close is not None:
                true_range = max(true_range, abs(high - previous_close), abs(low - previous_close))
            ranges.append(true_range)
            previous_close = float(bar.close)
        atr = sum(ranges[: self.period]) / self.period
        for true_range in ranges[self.period :]:
            atr = ((atr * (self.period - 1)) + true_range) / self.period
        return FeatureResult(
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            parameters=parameters,
            values={"atr": atr, "atr_percent": atr / float(series.bars[-1].close)},
            timeframe=series.timeframe,
            as_of=series.bars[-1].close_time,
            valid=True,
        )


@dataclass(frozen=True)
class ReturnFeature:
    lookback: int = 1
    feature_name: str = "return"
    feature_version: str = "return.simple.v1"

    def compute(self, series: MarketDataSeries) -> FeatureResult:
        parameters = {"lookback": self.lookback}
        if self.lookback < 1 or len(series.bars) <= self.lookback:
            return _invalid(self.feature_name, self.feature_version, series, parameters)
        previous = float(series.bars[-1 - self.lookback].close)
        current = float(series.bars[-1].close)
        value = (current / previous) - 1.0
        return FeatureResult(
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            parameters=parameters,
            values={"return": value},
            timeframe=series.timeframe,
            as_of=series.bars[-1].close_time,
            valid=True,
        )


@dataclass(frozen=True)
class VolatilityFeature:
    period: int
    feature_name: str = "realized_volatility"
    feature_version: str = "realized-volatility.v1"

    def compute(self, series: MarketDataSeries) -> FeatureResult:
        parameters = {"period": self.period}
        closes = [float(bar.close) for bar in series.bars]
        if self.period < 2 or len(closes) <= self.period:
            return _invalid(self.feature_name, self.feature_version, series, parameters)
        returns = [
            math.log(current / previous)
            for previous, current in zip(closes, closes[1:], strict=False)
        ]
        value = statistics.pstdev(returns[-self.period :])
        return FeatureResult(
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            parameters=parameters,
            values={"volatility": value},
            timeframe=series.timeframe,
            as_of=series.bars[-1].close_time,
            valid=True,
        )


@dataclass(frozen=True)
class VolumeTrendFeature:
    short_period: int
    long_period: int
    feature_name: str = "volume_trend"
    feature_version: str = "volume-trend.v1"

    def compute(self, series: MarketDataSeries) -> FeatureResult:
        parameters = {"short_period": self.short_period, "long_period": self.long_period}
        if (
            self.short_period < 1
            or self.long_period <= self.short_period
            or len(series.bars) < self.long_period
        ):
            return _invalid(self.feature_name, self.feature_version, series, parameters)
        volumes = [float(bar.volume) for bar in series.bars]
        short_mean = sum(volumes[-self.short_period :]) / self.short_period
        long_mean = sum(volumes[-self.long_period :]) / self.long_period
        ratio = 1.0 if long_mean == 0 else short_mean / long_mean
        return FeatureResult(
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            parameters=parameters,
            values={"ratio": ratio},
            timeframe=series.timeframe,
            as_of=series.bars[-1].close_time,
            valid=True,
        )
