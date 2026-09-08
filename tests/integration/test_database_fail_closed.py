from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from tests.conftest import DatabaseHarness
from tests.support import (
    NOW,
    encode_payload,
    hub_client,
    reason_code,
    signal_payload,
    signed_headers,
)

from tomiris_hub.core.clock import FakeClock
from tomiris_hub.database.models import Nonce, Signal
from tomiris_hub.services.signal_ingestion import SignalIngestionService


async def test_transaction_failure_rolls_back_nonce_and_signal(
    clean_database: DatabaseHarness,
) -> None:
    async def fail_after_nonce_flush(_: object) -> None:
        raise SQLAlchemyError("forced transaction failure")

    service = SignalIngestionService(FakeClock(NOW), 300, fail_after_nonce_flush)
    body = encode_payload(signal_payload())
    async with hub_client(clean_database.url, ingestion=service) as client:
        response = await client.post("/v1/signals", content=body, headers=signed_headers(body))
    assert response.status_code == 503
    assert reason_code(response) == "DATABASE_UNAVAILABLE"
    async with clean_database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Nonce)) == 0
        assert await session.scalar(select(func.count()).select_from(Signal)) == 0


async def test_database_down_has_no_false_accepted_and_readiness_is_503() -> None:
    unavailable_url = "postgresql+asyncpg://tomiris:tomiris@127.0.0.1:1/tomiris"
    body = encode_payload(signal_payload())
    async with hub_client(unavailable_url) as client:
        readiness = await client.get("/health/ready")
        ingestion = await client.post("/v1/signals", content=body, headers=signed_headers(body))
    assert readiness.status_code == 503
    assert ingestion.status_code == 503
    assert reason_code(ingestion) == "DATABASE_UNAVAILABLE"
