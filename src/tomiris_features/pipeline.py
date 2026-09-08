from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tomiris_features.indicators import (
    ATRFeature,
    EMAFeature,
    MACDFeature,
    ReturnFeature,
    RSIFeature,
    VolatilityFeature,
    VolumeTrendFeature,
)
from tomiris_features.models import FeatureResult
from tomiris_market_data.models import MarketDataSeries


class FeaturePipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ema_fast: int = Field(default=20, ge=2, le=500)
    ema_slow: int = Field(default=50, ge=3, le=800)
    rsi_period: int = Field(default=14, ge=2, le=100)
    macd_fast: int = Field(default=12, ge=2, le=100)
    macd_slow: int = Field(default=26, ge=3, le=200)
    macd_signal: int = Field(default=9, ge=2, le=100)
    atr_period: int = Field(default=14, ge=2, le=100)
    volatility_period: int = Field(default=20, ge=2, le=200)
    volume_short_period: int = Field(default=5, ge=1, le=100)
    volume_long_period: int = Field(default=20, ge=2, le=500)
    return_lookback: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def validate_periods(self) -> FeaturePipelineConfig:
        if self.ema_slow <= self.ema_fast:
            raise ValueError("ema_slow must exceed ema_fast")
        if self.macd_slow <= self.macd_fast:
            raise ValueError("macd_slow must exceed macd_fast")
        if self.volume_long_period <= self.volume_short_period:
            raise ValueError("volume_long_period must exceed volume_short_period")
        return self


class TechnicalFeaturePipeline:
    pipeline_version = "technical-pipeline.v1"

    def __init__(self, config: FeaturePipelineConfig) -> None:
        self.config = config
        self.features = (
            EMAFeature(config.ema_fast),
            EMAFeature(config.ema_slow),
            RSIFeature(config.rsi_period),
            MACDFeature(config.macd_fast, config.macd_slow, config.macd_signal),
            ATRFeature(config.atr_period),
            ReturnFeature(config.return_lookback),
            VolatilityFeature(config.volatility_period),
            VolumeTrendFeature(config.volume_short_period, config.volume_long_period),
        )

    def compute(self, series: MarketDataSeries) -> tuple[FeatureResult, ...]:
        return tuple(feature.compute(series) for feature in self.features)
