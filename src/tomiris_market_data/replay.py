from __future__ import annotations

from pydantic import TypeAdapter

from tomiris_market_data.contracts import NormalizedMarketEvent
from tomiris_market_data.serialization import canonical_json_bytes, canonical_sha256

_EVENT_ADAPTER = TypeAdapter(NormalizedMarketEvent)


def serialize_event(event: NormalizedMarketEvent) -> bytes:
    return canonical_json_bytes(event)


def deserialize_event(payload: bytes | str) -> NormalizedMarketEvent:
    return _EVENT_ADAPTER.validate_json(payload)


def replay_fingerprint(events: tuple[NormalizedMarketEvent, ...]) -> str:
    ordered = tuple(sorted(events, key=lambda event: (event.event_time, event.event_id)))
    return canonical_sha256(ordered)
