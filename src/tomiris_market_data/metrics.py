from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class MarketDataMetrics:
    counters: dict[tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    observations: dict[tuple[str, str, str], list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def increment(self, name: str, provider: str, asset: str) -> None:
        self.counters[(name, provider, asset)] += 1

    def observe_latency(self, provider: str, asset: str, milliseconds: float) -> None:
        self.observations[("market_data_latency", provider, asset)].append(milliseconds)
