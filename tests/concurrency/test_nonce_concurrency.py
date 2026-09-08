from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from tests.conftest import DatabaseHarness
from tests.support import encode_payload, hub_client, signal_payload, signed_headers

from tomiris_hub.database.models import Nonce, Signal


async def test_ten_identical_concurrent_requests_accept_at_most_one(
    clean_database: DatabaseHarness,
) -> None:
    body = encode_payload(signal_payload())
    headers = signed_headers(body, nonce="concurrent_nonce_123456789012345")
    async with hub_client(clean_database.url) as client:
        responses = await asyncio.gather(
            *[client.post("/v1/signals", content=body, headers=headers) for _ in range(10)]
        )
    statuses = [response.status_code for response in responses]
    assert statuses.count(202) == 1
    assert statuses.count(409) == 9
    async with clean_database.session_factory() as session:
        signal_count = await session.scalar(select(func.count()).select_from(Signal))
        nonce_count = await session.scalar(select(func.count()).select_from(Nonce))
    assert signal_count == 1
    assert nonce_count == 1
