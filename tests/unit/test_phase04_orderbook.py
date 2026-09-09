from __future__ import annotations

from decimal import Decimal

from tests.phase04_support import ETH_FUTURES, book_delta, book_snapshot

from tomiris_market_data.buffer import BufferPolicy
from tomiris_market_data.orderbook import (
    DeltaApplyResult,
    OrderBookSynchronizer,
    OrderBookSyncState,
)


async def test_orderbook_golden_snapshot_buffered_and_live_deltas() -> None:
    synchronizer = OrderBookSynchronizer(ETH_FUTURES, "fixture-provider")
    assert await synchronizer.buffer_delta(book_delta(101, 102, previous_id=100)) == "BUFFERED"
    view = await synchronizer.bootstrap(book_snapshot())
    assert view.state == OrderBookSyncState.SYNCED
    assert view.last_update_id == 102
    assert view.bids[0].quantity == Decimal("4")
    assert (
        await synchronizer.apply_delta(
            book_delta(103, 103, previous_id=102, bid_price="100.5", bid_quantity="1")
        )
        == DeltaApplyResult.APPLIED
    )
    assert await synchronizer.apply_delta(book_delta(101, 102)) == "DUPLICATE_OR_OLD"
    final = await synchronizer.read()
    assert final.last_update_id == 103
    assert final.bids[0].price == Decimal("100.5")
    assert final.safe_for_analysis is True


async def test_gap_fails_closed_and_fresh_snapshot_recovers() -> None:
    synchronizer = OrderBookSynchronizer(ETH_FUTURES, "fixture-provider")
    await synchronizer.bootstrap(book_snapshot())
    assert await synchronizer.apply_delta(book_delta(101, 101, previous_id=100)) == "APPLIED"
    assert await synchronizer.apply_delta(book_delta(103, 103, previous_id=102)) == "GAP"
    failed = await synchronizer.read()
    assert failed.state == OrderBookSyncState.OUT_OF_SYNC
    assert failed.safe_for_analysis is False
    assert await synchronizer.apply_delta(book_delta(104, 104, previous_id=103)) == "BUFFERED"

    async def fetch_fresh_snapshot():  # type: ignore[no-untyped-def]
        return book_snapshot(last_update_id=103)

    recovered = await synchronizer.recover(fetch_fresh_snapshot)
    assert recovered.state == OrderBookSyncState.SYNCED
    assert recovered.last_update_id == 104


async def test_disconnect_requires_resynchronization() -> None:
    synchronizer = OrderBookSynchronizer(ETH_FUTURES, "fixture-provider")
    await synchronizer.bootstrap(book_snapshot())
    await synchronizer.mark_disconnected()
    assert (await synchronizer.read()).state == OrderBookSyncState.RECONNECTING
    assert await synchronizer.apply_delta(book_delta(101, 101, previous_id=100)) == "BUFFERED"
    assert (await synchronizer.read()).safe_for_analysis is False

    async def fetch_fresh_snapshot():  # type: ignore[no-untyped-def]
        return book_snapshot()

    assert (await synchronizer.recover(fetch_fresh_snapshot)).safe_for_analysis is True


async def test_recovery_buffer_overflow_is_bounded_and_fail_closed() -> None:
    synchronizer = OrderBookSynchronizer(
        ETH_FUTURES,
        "fixture-provider",
        buffer_policy=BufferPolicy(max_events=1, max_bytes=10_000, max_duration_seconds=30),
    )
    assert await synchronizer.buffer_delta(book_delta(101, 101)) == "BUFFERED"
    assert await synchronizer.buffer_delta(book_delta(102, 102)) == "BUFFER_OVERFLOW"
    assert synchronizer.buffer.items == ()
    assert (await synchronizer.read()).state == OrderBookSyncState.OUT_OF_SYNC


async def test_same_snapshot_and_delta_sequence_is_deterministic() -> None:
    async def build() -> object:
        synchronizer = OrderBookSynchronizer(ETH_FUTURES, "fixture-provider")
        await synchronizer.bootstrap(book_snapshot())
        await synchronizer.apply_delta(book_delta(101, 101, previous_id=100))
        return await synchronizer.read()

    assert await build() == await build()
