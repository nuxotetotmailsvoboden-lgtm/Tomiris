from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_agent_roles.metrics import AnalysisMetrics
from tomiris_agent_roles.models import (
    AgentAnalysisResult,
    AgentDefinition,
    AnalysisDataRange,
    AnalyticalEvidence,
    MomentumState,
    RoleInput,
    TimeframeAnalysis,
    TrendState,
    VolatilityState,
)
from tomiris_core_contracts.signals import Bias
from tomiris_features.models import FeatureResult
from tomiris_features.pipeline import FeaturePipelineConfig, TechnicalFeaturePipeline
from tomiris_market_data.models import DataQualityOutcome, MarketDataSeries, Timeframe


class TechnicalRoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pipeline: FeaturePipelineConfig = Field(default_factory=FeaturePipelineConfig)
    timeframe_weights: dict[Timeframe, float] = Field(
        default_factory=lambda: {
            Timeframe.D1: 0.35,
            Timeframe.H4: 0.30,
            Timeframe.H1: 0.20,
            Timeframe.M15: 0.15,
        }
    )
    neutral_threshold: float = Field(default=0.18, gt=0, lt=1)
    strong_trend_threshold: float = Field(default=0.65, gt=0, le=1)
    rsi_bullish: float = Field(default=55, gt=50, lt=100)
    rsi_bearish: float = Field(default=45, gt=0, lt=50)
    high_atr_percent: float = Field(default=0.04, gt=0, lt=1)
    extreme_atr_percent: float = Field(default=0.08, gt=0, lt=2)
    high_realized_volatility: float = Field(default=0.03, gt=0, lt=1)
    extreme_realized_volatility: float = Field(default=0.07, gt=0, lt=2)
    range_ema_atr_ratio: float = Field(default=0.25, gt=0, le=2)
    swing_lookback: int = Field(default=10, ge=2, le=100)

    @field_validator("timeframe_weights")
    @classmethod
    def validate_weights(cls, values: dict[Timeframe, float]) -> dict[Timeframe, float]:
        if not values or any(value <= 0 for value in values.values()):
            raise ValueError("timeframe weights must be positive")
        return values

    @model_validator(mode="after")
    def validate_thresholds(self) -> TechnicalRoleConfig:
        if self.rsi_bearish >= self.rsi_bullish:
            raise ValueError("bearish RSI threshold must be below bullish threshold")
        if self.extreme_atr_percent <= self.high_atr_percent:
            raise ValueError("extreme ATR threshold must exceed high threshold")
        if self.extreme_realized_volatility <= self.high_realized_volatility:
            raise ValueError("extreme realized-volatility threshold must exceed high threshold")
        return self


@dataclass(frozen=True)
class _TimeframeComputation:
    state: TimeframeAnalysis
    evidence: tuple[AnalyticalEvidence, ...]


class TechnicalAnalysisEngine:
    """Transparent deterministic scoring shared by BTC, ETH and SOL pilot roles."""

    def __init__(
        self,
        config: TechnicalRoleConfig,
        *,
        evidence_type: str,
        metrics: AnalysisMetrics | None = None,
    ) -> None:
        self.config = config
        self.pipeline = TechnicalFeaturePipeline(config.pipeline)
        self.evidence_type = evidence_type
        self.metrics = metrics or AnalysisMetrics()

    def analyze(
        self,
        definition: AgentDefinition,
        role_input: RoleInput,
        *,
        role_version: str,
    ) -> AgentAnalysisResult:
        asset = role_input.context.task.asset
        try:
            if any(series.instrument != asset for series in role_input.market_data.series):
                raise ValueError("market-data asset isolation failure")
            expected = {
                (requirement.instrument, requirement.timeframe)
                for requirement in definition.required_data
            }
            actual = {
                (series.instrument, series.timeframe) for series in role_input.market_data.series
            }
            if actual != expected or len(actual) != len(role_input.market_data.series):
                return self.abstain(
                    definition,
                    role_input,
                    role_version=role_version,
                    reason="INSUFFICIENT_HISTORY",
                    quality=DataQualityOutcome.INSUFFICIENT,
                )
            computations = tuple(
                self._analyze_timeframe(series) for series in role_input.market_data.series
            )
            states = tuple(item.state for item in computations)
            evidence = tuple(
                evidence_item
                for computation in computations
                for evidence_item in computation.evidence
            )[: definition.limits.get("max_evidence_items", 16)]
            if not states:
                return self.abstain(
                    definition,
                    role_input,
                    role_version=role_version,
                    reason="INSUFFICIENT_HISTORY",
                    quality=DataQualityOutcome.INSUFFICIENT,
                )
            weights = [self.config.timeframe_weights.get(state.timeframe, 1.0) for state in states]
            weighted_score = sum(
                state.score * weight for state, weight in zip(states, weights, strict=True)
            ) / sum(weights)
            positives = sum(state.score > self.config.neutral_threshold for state in states)
            negatives = sum(state.score < -self.config.neutral_threshold for state in states)
            reason_codes: list[str] = []
            if positives and negatives:
                reason_codes.append("TIMEFRAME_CONFLICT")
            if any(
                state.volatility in {VolatilityState.HIGH, VolatilityState.EXTREME}
                for state in states
            ):
                reason_codes.append("HIGH_VOLATILITY")
            if abs(weighted_score) < self.config.neutral_threshold or (positives and negatives):
                bias = Bias.NEUTRAL
                reason_codes.append("NO_CLEAR_EDGE")
                confidence = min(
                    0.60,
                    max(0.0, 1.0 - abs(weighted_score) / self.config.neutral_threshold) * 0.60,
                )
            else:
                bias = Bias.LONG if weighted_score > 0 else Bias.SHORT
                matching = positives if bias == Bias.LONG else negatives
                agreement = matching / len(states)
                normalized_strength = min(
                    1.0, abs(weighted_score) / self.config.strong_trend_threshold
                )
                confidence = min(1.0, normalized_strength * 0.65 + agreement * 0.35)
            provider = ",".join(
                sorted({series.provider for series in role_input.market_data.series})
            )
            data_as_of = max(series.bars[-1].close_time for series in role_input.market_data.series)
            result = AgentAnalysisResult(
                analysis_schema_version=definition.analysis_schema_version,
                role_id=definition.role_id,
                role_version=role_version,
                config_version=definition.config_version,
                feature_pipeline_version=self.pipeline.pipeline_version,
                snapshot_id=role_input.context.snapshot_id,
                asset=asset,
                bias=bias,
                confidence=round(confidence, 6),
                data_quality=DataQualityOutcome.VALID,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                timeframe_states=states,
                evidence=evidence,
                data_ranges=self._data_ranges(role_input),
                data_provider=provider,
                data_as_of=data_as_of,
                analysis_as_of=role_input.context.as_of,
            )
            return result
        except (KeyError, ValueError):
            self.metrics.increment("feature_compute_failures_total", definition.role_id, asset)
            return self.abstain(
                definition,
                role_input,
                role_version=role_version,
                reason="FEATURE_FAILURE",
                quality=DataQualityOutcome.INVALID,
            )

    def abstain(
        self,
        definition: AgentDefinition,
        role_input: RoleInput,
        *,
        role_version: str,
        reason: str,
        quality: DataQualityOutcome,
    ) -> AgentAnalysisResult:
        providers = sorted({item.provider for item in role_input.market_data.series})
        timestamps = [item.bars[-1].close_time for item in role_input.market_data.series]
        return AgentAnalysisResult(
            analysis_schema_version=definition.analysis_schema_version,
            role_id=definition.role_id,
            role_version=role_version,
            config_version=definition.config_version,
            feature_pipeline_version=self.pipeline.pipeline_version,
            snapshot_id=role_input.context.snapshot_id,
            asset=role_input.context.task.asset,
            bias=Bias.ABSTAIN,
            confidence=0,
            data_quality=quality,
            reason_codes=(reason,),
            data_ranges=self._data_ranges(role_input),
            data_provider=",".join(providers) or "unavailable",
            data_as_of=max(timestamps, default=role_input.context.as_of),
            analysis_as_of=role_input.context.as_of,
        )

    @staticmethod
    def _data_ranges(role_input: RoleInput) -> tuple[AnalysisDataRange, ...]:
        return tuple(
            AnalysisDataRange(
                provider=series.provider,
                instrument=series.instrument,
                timeframe=series.timeframe,
                first_bar_at=series.bars[0].open_time,
                last_bar_at=series.bars[-1].close_time,
                bar_count=len(series.bars),
            )
            for series in role_input.market_data.series
        )

    def _analyze_timeframe(self, series: MarketDataSeries) -> _TimeframeComputation:
        features = self.pipeline.compute(series)
        invalid = [feature for feature in features if not feature.valid]
        if invalid:
            raise ValueError(invalid[0].reason_code or "FEATURE_FAILURE")
        fast = self._ema(features, self.config.pipeline.ema_fast)
        slow = self._ema(features, self.config.pipeline.ema_slow)
        rsi = self._feature(features, "rsi").values["rsi"]
        macd = self._feature(features, "macd").values
        atr = self._feature(features, "atr").values
        realized_volatility = self._feature(features, "realized_volatility").values["volatility"]
        latest_return = self._feature(features, "return").values["return"]
        volume_ratio = self._feature(features, "volume_trend").values["ratio"]
        close = float(series.bars[-1].close)

        trend_score = 0.0
        if close > fast > slow:
            trend, trend_score = TrendState.STRONG_UP, 1.0
        elif close > fast and close > slow:
            trend, trend_score = TrendState.UP, 0.6
        elif close < fast < slow:
            trend, trend_score = TrendState.STRONG_DOWN, -1.0
        elif close < fast and close < slow:
            trend, trend_score = TrendState.DOWN, -0.6
        else:
            trend = TrendState.NEUTRAL

        momentum_score = 0.0
        if rsi >= self.config.rsi_bullish and macd["histogram"] > 0:
            momentum, momentum_score = MomentumState.BULLISH, 1.0
        elif rsi <= self.config.rsi_bearish and macd["histogram"] < 0:
            momentum, momentum_score = MomentumState.BEARISH, -1.0
        else:
            momentum = MomentumState.NEUTRAL

        atr_percent = atr["atr_percent"]
        if (
            atr_percent >= self.config.extreme_atr_percent
            or realized_volatility >= self.config.extreme_realized_volatility
        ):
            volatility = VolatilityState.EXTREME
        elif (
            atr_percent >= self.config.high_atr_percent
            or realized_volatility >= self.config.high_realized_volatility
        ):
            volatility = VolatilityState.HIGH
        elif atr_percent < self.config.high_atr_percent / 3:
            volatility = VolatilityState.LOW
        else:
            volatility = VolatilityState.NORMAL
        volume_state = (
            "RISING" if volume_ratio > 1.10 else "FALLING" if volume_ratio < 0.90 else "NORMAL"
        )

        prior = series.bars[-1 - min(self.config.swing_lookback, len(series.bars) - 1) : -1]
        swing_score = 0.0
        if prior and close > max(float(bar.high) for bar in prior):
            swing_score = 1.0
        elif prior and close < min(float(bar.low) for bar in prior):
            swing_score = -1.0
        return_score = 1.0 if latest_return > 0 else -1.0 if latest_return < 0 else 0.0
        raw_score = (
            (trend_score * 0.45)
            + (momentum_score * 0.30)
            + (swing_score * 0.15)
            + (return_score * 0.10)
        )
        range_like = abs(fast - slow) < atr["atr"] * self.config.range_ema_atr_ratio
        if range_like and swing_score == 0:
            trend = TrendState.NEUTRAL
            raw_score *= 0.25
        score = min(1.0, max(-1.0, raw_score))
        state = TimeframeAnalysis(
            timeframe=series.timeframe,
            trend=trend,
            momentum=momentum,
            volatility=volatility,
            volume_state=volume_state,
            score=score,
        )
        timestamp = series.bars[-1].close_time
        provider = series.provider
        evidence = (
            self._evidence(
                series,
                timestamp,
                provider,
                self._ema_result(features, self.config.pipeline.ema_slow),
                f"close={close:.8g}; ema_slow={slow:.8g}; trend={trend.value}",
            ),
            self._evidence(
                series,
                timestamp,
                provider,
                self._feature(features, "rsi"),
                f"rsi={rsi:.6g}; momentum={momentum.value}",
            ),
            self._evidence(
                series,
                timestamp,
                provider,
                self._feature(features, "macd"),
                f"macd_histogram={macd['histogram']:.8g}",
            ),
            self._evidence(
                series,
                timestamp,
                provider,
                self._feature(features, "atr"),
                (
                    f"atr_percent={atr_percent:.8g}; "
                    f"realized_volatility={realized_volatility:.8g}; "
                    f"volatility={volatility.value}"
                ),
            ),
        )
        return _TimeframeComputation(state=state, evidence=evidence)

    @staticmethod
    def _feature(features: tuple[FeatureResult, ...], name: str) -> FeatureResult:
        return next(feature for feature in features if feature.feature_name == name)

    @staticmethod
    def _ema_result(features: tuple[FeatureResult, ...], period: int) -> FeatureResult:
        return next(
            feature
            for feature in features
            if feature.feature_name == "ema" and feature.parameters["period"] == period
        )

    def _ema(self, features: tuple[FeatureResult, ...], period: int) -> float:
        return self._ema_result(features, period).values["ema"]

    def _evidence(
        self,
        series: MarketDataSeries,
        timestamp: datetime,
        provider: str,
        feature: FeatureResult,
        observation: str,
    ) -> AnalyticalEvidence:
        return AnalyticalEvidence(
            evidence_type=self.evidence_type,
            summary=f"{series.instrument} {series.timeframe.value} {observation}",
            provider=provider,
            instrument=series.instrument,
            timeframe=series.timeframe,
            feature_name=feature.feature_name,
            feature_version=feature.feature_version,
            observed_at=timestamp,
            source_timestamp=timestamp,
            observation=observation,
        )
