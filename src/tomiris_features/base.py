from __future__ import annotations

from typing import Protocol

from tomiris_features.models import FeatureResult
from tomiris_market_data.models import MarketDataSeries


class Feature(Protocol):
    feature_name: str
    feature_version: str

    def compute(self, series: MarketDataSeries) -> FeatureResult: ...
