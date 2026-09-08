from __future__ import annotations

from sqlalchemy import func, select
from tests.conftest import DatabaseHarness
from tests.support import encode_payload, hub_client, reason_code, signal_payload, signed_headers

from tomiris_hub.database.models import Nonce, Signal


async def test_replay_is_rejected_after_hub_restart(clean_database: DatabaseHarness) -> None:
    body = encode_payload(signal_payload())
    headers = signed_headers(body, nonce="restart_nonce_123456789012345678")
    async with hub_client(clean_database.url) as first_process:
        accepted = await first_process.post("/v1/signals", content=body, headers=headers)
    async with hub_client(clean_database.url) as restarted_process:
        replay = await restarted_process.post("/v1/signals", content=body, headers=headers)
    assert accepted.status_code == 202
    assert replay.status_code == 409
    assert reason_code(replay) == "REPLAY_OR_DUPLICATE"
    async with clean_database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Signal)) == 1
        assert await session.scalar(select(func.count()).select_from(Nonce)) == 1
