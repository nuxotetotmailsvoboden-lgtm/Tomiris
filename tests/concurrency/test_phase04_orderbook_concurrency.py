from __future__ import annotations

import asyncio

from tests.phase04_support import ETH_FUTURES, book_delta, book_snapshot

from tomiris_market_data.orderbook import OrderBookSynchronizer, OrderBookSyncState


async def test_concurrent_delta_reads_and_controlled_resync_are_atomic() -> None:
    synchronizer = OrderBookSynchronizer(ETH_FUTURES, "fixture-provider")
    await synchronizer.bootstrap(book_snapshot())
    halfway = asyncio.Event()
    resume = asyncio.Event()
    finished = asyncio.Event()
    observed = []

    async def writer() -> None:
        for sequence in range(101, 301):
            await synchronizer.apply_delta(book_delta(sequence, sequence, previous_id=sequence - 1))
            if sequence == 200:
                halfway.set()
                await resume.wait()
            await asyncio.sleep(0)
        finished.set()

    async def reader() -> None:
        while not finished.is_set():
            view = await synchronizer.read()
            if view.bids and view.asks:
                assert view.bids[0].price < view.asks[0].price
            observed.append(view.state)
            await asyncio.sleep(0)

    async def resync() -> None:
        await halfway.wait()
        await synchronizer.mark_disconnected()
        assert (await synchronizer.read()).safe_for_analysis is False
        recovered = await synchronizer.bootstrap(book_snapshot(last_update_id=200))
        assert recovered.state == OrderBookSyncState.SYNCED
        resume.set()

    await asyncio.gather(writer(), reader(), resync())
    final = await synchronizer.read()
    assert final.state == OrderBookSyncState.SYNCED
    assert final.last_update_id == 300
    assert observed
