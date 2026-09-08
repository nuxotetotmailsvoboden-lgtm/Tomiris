from __future__ import annotations

import random
from collections.abc import Callable


class ExponentialBackoff:
    def __init__(
        self,
        base_seconds: float,
        max_seconds: float,
        *,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.base_seconds = base_seconds
        self.max_seconds = max_seconds
        self.random_value = random_value

    def delay(self, attempt: int) -> float:
        bounded = min(self.max_seconds, self.base_seconds * (2 ** max(0, attempt - 1)))
        return float(bounded * (0.5 + (0.5 * self.random_value())))
