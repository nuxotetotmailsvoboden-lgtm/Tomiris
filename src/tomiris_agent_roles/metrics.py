from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class AnalysisMetrics:
    counters: dict[tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    observations: dict[tuple[str, str, str], list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def increment(self, name: str, role_id: str, asset: str) -> None:
        self.counters[(name, role_id, asset)] += 1

    def observe_latency(self, role_id: str, asset: str, milliseconds: float) -> None:
        self.observations[("agent_analysis_latency", role_id, asset)].append(milliseconds)
