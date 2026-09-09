from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.phase04_support import ETH_FUTURES, NOW, mark_event

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.errors import SnapshotValidationError
from tomiris_market_data.identity import CanonicalInstrument
from tomiris_market_data.models import DataQualityOutcome
from tomiris_market_data.quality import MarketDataQualityEngine, MarketDataQualityPolicy
from tomiris_market_data.replay import deserialize_event, replay_fingerprint, serialize_event
from tomiris_market_data.snapshot import (
    SnapshotRequirement,
    SnapshotRequirementItem,
    VerifiedMarketSnapshot,
    VerifiedMarketSnapshotBuilder,
)
from tomiris_market_data.store import InMemoryRecentMarketEventStore
from tomiris_market_data.time import (
    ClockDriftMonitor,
    ClockDriftPolicy,
    DeterministicClock,
)


def requirement(*, optional_funding: bool = False) -> SnapshotRequirement:
    items = [
        SnapshotRequirementItem(
            instrument=ETH_FUTURES,
            data_type=MarketDataType.MARK_PRICE,
            required=True,
            max_age_seconds=10,
        )
    ]
    if optional_funding:
        items.append(
            SnapshotRequirementItem(
                instrument=ETH_FUTURES,
                data_type=MarketDataType.FUNDING_RATE,
                required=False,
                max_age_seconds=60,
            )
        )
    return SnapshotRequirement(items=tuple(items), max_temporal_skew_seconds=2)


def valid_quality(event_id: str, event: object) -> object:
    assert hasattr(event, "event_time")
    return MarketDataQualityEngine().evaluate_event(  # type: ignore[arg-type]
        event,  # type: ignore[arg-type]
        observed_at=NOW,
        policy=MarketDataQualityPolicy(max_age_seconds=10),
    )


async def build_snapshot(event: object, *, optional_funding: bool = False) -> object:
    store = InMemoryRecentMarketEventStore(max_events=10, max_bytes=100_000)
    await store.append(event)  # type: ignore[arg-type]
    report = valid_quality(event.event_id, event)  # type: ignore[attr-defined]
    return await VerifiedMarketSnapshotBuilder(store, clock=DeterministicClock(NOW)).build(
        snapshot_id=uuid4(),
        as_of=NOW,
        requirement=requirement(optional_funding=optional_funding),
        quality_reports={event.event_id: report},  # type: ignore[attr-defined,dict-item]
    )


async def test_snapshot_is_verified_and_optional_missing_is_degraded() -> None:
    event = mark_event()
    snapshot = await build_snapshot(event, optional_funding=True)
    assert snapshot.manifest.quality_state == DataQualityOutcome.DEGRADED  # type: ignore[attr-defined]
    assert snapshot.manifest.safe_for_analysis is True  # type: ignore[attr-defined]
    assert snapshot.manifest.missing_optional == (  # type: ignore[attr-defined]
        "BINANCE:USDT_M_FUTURES:ETHUSDT/FUNDING_RATE",
    )


async def test_snapshot_temporal_cutoff_excludes_lookahead() -> None:
    store = InMemoryRecentMarketEventStore(max_events=10, max_bytes=100_000)
    future = mark_event(event_id="future", event_time=NOW + timedelta(seconds=1))
    await store.append(future)
    snapshot = await VerifiedMarketSnapshotBuilder(store, clock=DeterministicClock(NOW)).build(
        snapshot_id=uuid4(),
        as_of=NOW,
        requirement=requirement(),
        quality_reports={},
    )
    assert snapshot.events == ()
    assert snapshot.manifest.quality_state == DataQualityOutcome.INSUFFICIENT
    assert snapshot.manifest.safe_for_analysis is False
    with pytest.raises(SnapshotValidationError) as caught:
        snapshot.require_analysis_safe()
    assert caught.value.code == "SNAPSHOT_NOT_ANALYSIS_SAFE"


async def test_unsafe_clock_vetoes_otherwise_valid_snapshot() -> None:
    event = mark_event()
    store = InMemoryRecentMarketEventStore(max_events=10, max_bytes=100_000)
    await store.append(event)
    quality = MarketDataQualityEngine().evaluate_event(event, observed_at=NOW)
    drift = ClockDriftMonitor(
        ClockDriftPolicy(degraded_threshold_ms=100, unsafe_threshold_ms=200)
    ).measure(
        provider="fixture-provider",
        exchange_time=NOW + timedelta(seconds=1),
        request_started_at=NOW,
        response_received_at=NOW,
    )
    snapshot = await VerifiedMarketSnapshotBuilder(store, clock=DeterministicClock(NOW)).build(
        snapshot_id=uuid4(),
        as_of=NOW,
        requirement=requirement(),
        quality_reports={event.event_id: quality},
        clock_measurements=(drift,),
    )
    assert snapshot.manifest.quality_state == DataQualityOutcome.INVALID
    assert "CLOCK_DRIFT_UNSAFE" in snapshot.manifest.reason_codes


async def test_snapshot_content_fingerprint_is_stable_and_content_sensitive() -> None:
    first = await build_snapshot(mark_event(price="100"))
    second = await build_snapshot(mark_event(price="100"))
    changed = await build_snapshot(mark_event(price="101"))
    assert first.manifest.content_fingerprint == second.manifest.content_fingerprint  # type: ignore[attr-defined]
    assert first.manifest.content_fingerprint != changed.manifest.content_fingerprint  # type: ignore[attr-defined]


def test_event_serialization_round_trip_and_replay_fingerprint() -> None:
    event = mark_event()
    decoded = deserialize_event(serialize_event(event))
    assert decoded == event
    assert replay_fingerprint((event,)) == replay_fingerprint((decoded,))


async def test_manifest_component_hash_rejects_tampered_event() -> None:
    snapshot = await build_snapshot(mark_event(price="100"))
    original = snapshot.events[0]  # type: ignore[attr-defined]
    tampered_payload = original.payload.model_copy(update={"mark_price": "999"})
    tampered = original.model_copy(update={"payload": tampered_payload})
    with pytest.raises(ValidationError):
        VerifiedMarketSnapshot(manifest=snapshot.manifest, events=(tampered,))  # type: ignore[attr-defined]


async def test_recent_store_stays_bounded_under_thousands_of_events() -> None:
    store = InMemoryRecentMarketEventStore(max_events=250, max_bytes=2_000_000)
    instruments = tuple(
        CanonicalInstrument.binance_usdt_m(f"A{index:03d}USDT", f"A{index:03d}")
        for index in range(100)
    )
    for instrument_index, instrument in enumerate(instruments):
        for event_index in range(50):
            await store.append(
                mark_event(
                    event_id=f"mark-{instrument_index}-{event_index}",
                    price=str(100 + event_index),
                    instrument=instrument,
                )
            )
    assert store.event_count == 250
    assert store.byte_size <= 2_000_000
    latest_instrument_events = await store.query(
        instrument_id=instruments[-1].instrument_id,
        data_types=frozenset({MarketDataType.MARK_PRICE}),
        as_of=NOW,
        limit=100,
    )
    assert len(latest_instrument_events) == 50
