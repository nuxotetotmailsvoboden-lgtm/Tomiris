from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.identity import MarketType


@dataclass
class MarketDataPlaneMetrics:
    counters: dict[tuple[str, str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    observations: dict[tuple[str, str, str, str], list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def increment(
        self,
        name: str,
        provider: str,
        market_type: MarketType,
        data_type: MarketDataType,
    ) -> None:
        self.counters[(name, provider, market_type.value, data_type.value)] += 1

    def observe(
        self,
        name: str,
        provider: str,
        market_type: MarketType,
        data_type: MarketDataType,
        value: float,
    ) -> None:
        self.observations[(name, provider, market_type.value, data_type.value)].append(value)
