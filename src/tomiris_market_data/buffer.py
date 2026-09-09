from __future__ import annotations

from collections import deque

from pydantic import BaseModel, ConfigDict, Field

from tomiris_market_data.contracts import OrderBookDelta
from tomiris_market_data.errors import BufferOverflowError
from tomiris_market_data.serialization import canonical_json_bytes


class BufferPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_events: int = Field(default=2_000, ge=1, le=100_000)
    max_bytes: int = Field(default=8_000_000, ge=1_024, le=100_000_000)
    max_duration_seconds: float = Field(default=30, gt=0, le=600)


class BoundedOrderBookDeltaBuffer:
    def __init__(self, policy: BufferPolicy | None = None) -> None:
        self.policy = policy or BufferPolicy()
        self._items: deque[tuple[OrderBookDelta, int]] = deque()
        self._bytes = 0

    @property
    def items(self) -> tuple[OrderBookDelta, ...]:
        return tuple(item for item, _size in self._items)

    @property
    def byte_size(self) -> int:
        return self._bytes

    def append(self, delta: OrderBookDelta) -> None:
        size = len(canonical_json_bytes(delta))
        timestamps = [item.exchange_timestamp for item, _size in self._items]
        timestamps.append(delta.exchange_timestamp)
        duration = (max(timestamps) - min(timestamps)).total_seconds()
        if (
            len(self._items) + 1 > self.policy.max_events
            or self._bytes + size > self.policy.max_bytes
            or duration > self.policy.max_duration_seconds
        ):
            self.clear()
            raise BufferOverflowError(
                "BUFFER_OVERFLOW",
                "order-book recovery buffer exceeded a configured bound",
            )
        self._items.append((delta, size))
        self._bytes += size

    def clear(self) -> None:
        self._items.clear()
        self._bytes = 0
