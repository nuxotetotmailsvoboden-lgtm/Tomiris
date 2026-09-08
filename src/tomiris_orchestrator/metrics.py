from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class OperationalMetrics:
    """Small dependency-free metric sink; exporters can be added in a later phase."""

    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    observations: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] += amount

    def observe(self, name: str, value: float) -> None:
        self.observations[name].append(value)

    def snapshot(self) -> dict[str, object]:
        return {
            "counters": dict(self.counters),
            "observations": {name: list(values) for name, values in self.observations.items()},
        }
