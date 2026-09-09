from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import NormalizedMarketEvent
from tomiris_market_data.identity import MarketType
from tomiris_market_data.plane_metrics import MarketDataPlaneMetrics
from tomiris_market_data.time import SystemUTCClock, TimeSource


class StreamState(StrEnum):
    CONNECTING = "CONNECTING"
    LIVE = "LIVE"
    STALE = "STALE"
    RECONNECTING = "RECONNECTING"
    OUT_OF_SYNC = "OUT_OF_SYNC"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class StreamSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    queue_max_events: int = Field(default=2_000, ge=1, le=100_000)
    stale_after_seconds: float = Field(default=30, gt=0, le=3_600)
    reconnect_max_attempts: int = Field(default=10, ge=1, le=100)
    reconnect_base_seconds: float = Field(default=0.25, gt=0, le=30)
    reconnect_max_seconds: float = Field(default=10, gt=0, le=300)

    @model_validator(mode="after")
    def ordered_backoff(self) -> StreamSettings:
        if self.reconnect_max_seconds < self.reconnect_base_seconds:
            raise ValueError("reconnect maximum must not be below base delay")
        return self


class MarketDataSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str = Field(min_length=5, max_length=128)
    data_types: tuple[MarketDataType, ...] = Field(min_length=1, max_length=20)
    depth_levels: int | None = Field(default=None, ge=1, le=5_000)

    @field_validator("data_types")
    @classmethod
    def unique_data_types(cls, values: tuple[MarketDataType, ...]) -> tuple[MarketDataType, ...]:
        if len(set(values)) != len(values):
            raise ValueError("subscription data types must be unique")
        return values


class MarketDataStreamFactory(Protocol):
    async def subscribe(self, subscription: MarketDataSubscription) -> MarketDataStream: ...


class StreamHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: StreamState
    connection_alive: bool
    data_fresh: bool
    last_event_at: datetime | None = None
    reason_code: str | None = None
    last_error_code: str | None = None


class StreamConnection(Protocol):
    def __aiter__(self) -> AsyncIterator[bytes | str]: ...

    async def close(self) -> None: ...


class StreamConnector(Protocol):
    async def connect(self) -> StreamConnection: ...


class MarketEventNormalizer(Protocol):
    def normalize(
        self, raw: bytes | str, *, received_at: datetime, processed_at: datetime
    ) -> tuple[NormalizedMarketEvent, ...]: ...


class MarketDataStream(Protocol):
    async def start(self) -> None: ...

    def events(self) -> AsyncIterator[NormalizedMarketEvent]: ...

    def health(self) -> StreamHealth: ...

    async def close(self) -> None: ...


StateCallback = Callable[[StreamState, str], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]


class ManagedMarketDataStream:
    """Provider-neutral bounded stream lifecycle with retry and cleanup."""

    def __init__(
        self,
        *,
        provider: str,
        market_type: MarketType,
        data_type: MarketDataType,
        connector: StreamConnector,
        normalizer: MarketEventNormalizer,
        settings: StreamSettings | None = None,
        clock: TimeSource | None = None,
        metrics: MarketDataPlaneMetrics | None = None,
        on_state_change: StateCallback | None = None,
        sleep: Sleep = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.provider = provider
        self.market_type = market_type
        self.data_type = data_type
        self.connector = connector
        self.normalizer = normalizer
        self.settings = settings or StreamSettings()
        self.clock = clock or SystemUTCClock()
        self.metrics = metrics or MarketDataPlaneMetrics()
        self.on_state_change = on_state_change
        self.sleep = sleep
        self.random_value = random_value
        self.state = StreamState.STOPPED
        self.reason_code: str | None = None
        self.last_event_at: datetime | None = None
        self.last_error_code: str | None = None
        self._queue: asyncio.Queue[NormalizedMarketEvent | None] = asyncio.Queue(
            maxsize=self.settings.queue_max_events
        )
        self._runner: asyncio.Task[None] | None = None
        self._connection: StreamConnection | None = None
        self._closing = False

    async def start(self) -> None:
        if self._runner is not None and not self._runner.done():
            return
        self._closing = False
        await self._set_state(StreamState.CONNECTING, "STREAM_STARTING")
        self._runner = asyncio.create_task(self._run(), name=f"market-stream:{self.provider}")

    async def _run(self) -> None:
        failures = 0
        try:
            while not self._closing:
                try:
                    self._connection = await self.connector.connect()
                    self.metrics.increment(
                        "market_stream_connections",
                        self.provider,
                        self.market_type,
                        self.data_type,
                    )
                    await self._set_state(StreamState.LIVE, "STREAM_CONNECTED")
                    received_one = False
                    async for raw in self._connection:
                        if self._closing:
                            break
                        now = self.clock.now()
                        events = self.normalizer.normalize(raw, received_at=now, processed_at=now)
                        for event in events:
                            if self._queue.full():
                                self.metrics.increment(
                                    "market_stream_dropped_total",
                                    self.provider,
                                    self.market_type,
                                    self.data_type,
                                )
                                await self._set_state(StreamState.OUT_OF_SYNC, "BUFFER_OVERFLOW")
                                raise RuntimeError("bounded stream queue overflow")
                            self._queue.put_nowait(event)
                            self.last_event_at = now
                            received_one = True
                            self.metrics.increment(
                                "market_stream_events_total",
                                self.provider,
                                self.market_type,
                                self.data_type,
                            )
                    if received_one:
                        failures = 0
                    if not self._closing:
                        raise ConnectionError("stream ended")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.last_error_code = getattr(exc, "code", type(exc).__name__.upper())
                    failures += 1
                    self.metrics.increment(
                        "market_stream_failures",
                        self.provider,
                        self.market_type,
                        self.data_type,
                    )
                    if failures >= self.settings.reconnect_max_attempts:
                        await self._set_state(StreamState.FAILED, "RECONNECT_EXHAUSTED")
                        break
                    await self._set_state(StreamState.RECONNECTING, "STREAM_DISCONNECTED")
                    self.metrics.increment(
                        "market_stream_reconnects",
                        self.provider,
                        self.market_type,
                        self.data_type,
                    )
                    bounded = min(
                        self.settings.reconnect_max_seconds,
                        self.settings.reconnect_base_seconds * (2 ** (failures - 1)),
                    )
                    await self.sleep(bounded * (0.5 + 0.5 * self.random_value()))
                finally:
                    if self._connection is not None:
                        await self._connection.close()
                        self._connection = None
        finally:
            if self.state != StreamState.FAILED:
                await self._set_state(StreamState.STOPPED, "STREAM_STOPPED")
            self._signal_end()

    async def events(self) -> AsyncIterator[NormalizedMarketEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    def health(self) -> StreamHealth:
        fresh = False
        state = self.state
        reason = self.reason_code
        if self.last_event_at is not None:
            age = (self.clock.now() - self.last_event_at).total_seconds()
            fresh = age <= self.settings.stale_after_seconds
            if state == StreamState.LIVE and not fresh:
                state = StreamState.STALE
                reason = "DATA_STALE"
        return StreamHealth(
            state=state,
            connection_alive=self.state == StreamState.LIVE,
            data_fresh=fresh,
            last_event_at=self.last_event_at,
            reason_code=reason,
            last_error_code=self.last_error_code,
        )

    async def close(self) -> None:
        self._closing = True
        if self._connection is not None:
            await self._connection.close()
        if self._runner is not None:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
            self._runner = None
        await self._set_state(StreamState.STOPPED, "STREAM_STOPPED")
        self._signal_end()

    async def _set_state(self, state: StreamState, reason: str) -> None:
        self.state = state
        self.reason_code = reason
        if self.on_state_change is not None:
            await self.on_state_change(state, reason)

    def _signal_end(self) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
