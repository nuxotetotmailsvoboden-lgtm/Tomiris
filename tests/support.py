from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from asgi_lifespan import LifespanManager

from tomiris_agent_sdk.signing import build_signed_headers
from tomiris_hub.application import create_app
from tomiris_hub.core.clock import Clock, FakeClock
from tomiris_hub.core.config import Settings
from tomiris_hub.services.signal_ingestion import SignalIngestionService

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
SECRET = "0123456789abcdef0123456789abcdef"  # noqa: S105 - test-only HMAC fixture
KEY_ID = "current"
VALID_SNAPSHOT_ID = UUID("10000000-0000-0000-0000-000000000001")
EXPIRED_SNAPSHOT_ID = UUID("10000000-0000-0000-0000-000000000002")
INVALID_SNAPSHOT_ID = UUID("10000000-0000-0000-0000-000000000003")
INCOMPATIBLE_SNAPSHOT_ID = UUID("10000000-0000-0000-0000-000000000004")
UNKNOWN_SNAPSHOT_ID = UUID("10000000-0000-0000-0000-000000000099")


def test_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": database_url,
        "app_env": "test",
        "tomiris_hub_ingest_key_id": KEY_ID,
        "tomiris_hub_ingest_secret": SECRET,
        "max_signal_request_bytes": 65_536,
        "database_connect_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def signal_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol_version": "1.0",
        "message_id": str(uuid4()),
        "agent_id": "TEST_AGENT_001",
        "agent_run_id": str(uuid4()),
        "snapshot_id": str(VALID_SNAPSHOT_ID),
        "asset": "TEST",
        "bias": "LONG",
        "confidence": 70,
        "impact": 25,
        "time_horizon": "phase-01-system-test",
        "evidence": [],
        "risk_flags": [],
        "data_timestamp": NOW.isoformat(),
        "analysis_timestamp": NOW.isoformat(),
        "signal_ttl_seconds": 30,
        "metadata": {"purpose": "system-test"},
    }
    payload.update(overrides)
    return payload


def encode_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def signed_headers(
    body: bytes,
    *,
    agent_id: str = "TEST_AGENT_001",
    secret: str = SECRET,
    key_id: str = KEY_ID,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    return build_signed_headers(
        agent_id,
        key_id,
        secret,
        "POST",
        "/v1/signals",
        body,
        timestamp=int(NOW.timestamp()) if timestamp is None else timestamp,
        nonce=nonce,
    )


@asynccontextmanager
async def hub_client(
    database_url: str,
    *,
    clock: Clock | None = None,
    ingestion: SignalIngestionService | None = None,
    **setting_overrides: Any,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        test_settings(database_url, **setting_overrides),
        clock=clock or FakeClock(NOW),
        ingestion=ingestion,
    )
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def reason_code(response: httpx.Response) -> str:
    return str(response.json()["detail"]["code"])
