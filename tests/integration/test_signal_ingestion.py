from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text
from tests.conftest import DatabaseHarness
from tests.support import (
    EXPIRED_SNAPSHOT_ID,
    INCOMPATIBLE_SNAPSHOT_ID,
    INVALID_SNAPSHOT_ID,
    NOW,
    UNKNOWN_SNAPSHOT_ID,
    encode_payload,
    hub_client,
    reason_code,
    signal_payload,
    signed_headers,
)

from tomiris_hub.database.models import AuditEvent, Nonce, Signal


async def _send(client: Any, payload: dict[str, Any], **header_options: Any) -> Any:
    body = encode_payload(payload)
    return await client.post(
        "/v1/signals", content=body, headers=signed_headers(body, **header_options)
    )


async def test_migrations_registry_and_valid_signal(clean_database: DatabaseHarness) -> None:
    payload = signal_payload(
        correlation_id="20000000-0000-0000-0000-000000000001",
        causation_id="20000000-0000-0000-0000-000000000002",
        evidence=[
            {
                "evidence_type": "test",
                "summary": "provenance contract system test",
                "source_type": "fixture",
                "source_id": "fixture-1",
                "provider": "tomiris-tests",
                "observed_at": NOW.isoformat(),
                "source_timestamp": NOW.isoformat(),
                "source_fingerprint": "sha256:fixture",
                "metadata": {},
            }
        ],
    )
    async with hub_client(clean_database.url) as client:
        response = await _send(client, payload)
        readiness = await client.get("/health/ready")
    assert response.status_code == 202
    assert readiness.status_code == 200
    async with clean_database.session_factory() as session:
        migration = await session.scalar(text("SELECT version_num FROM alembic_version"))
        signal = await session.scalar(select(Signal))
        audit = await session.scalar(select(AuditEvent).where(AuditEvent.outcome == "ACCEPTED"))
    assert migration == "0004_pilot_agents"
    assert signal is not None and signal.correlation_id == audit.correlation_id
    assert signal.snapshot_id == audit.snapshot_id
    assert signal.payload_json["evidence"][0]["provider"] == "tomiris-tests"


@pytest.mark.parametrize(
    ("payload_changes", "agent_id", "expected"),
    [
        ({"agent_id": "UNKNOWN_AGENT_001"}, "UNKNOWN_AGENT_001", "UNKNOWN_AGENT"),
        (
            {"agent_id": "DISABLED_AGENT_001"},
            "DISABLED_AGENT_001",
            "AGENT_DISABLED",
        ),
        ({}, "OTHER_AGENT_001", "AGENT_ID_MISMATCH"),
    ],
)
async def test_agent_authorization_matrix(
    clean_database: DatabaseHarness,
    payload_changes: dict[str, Any],
    agent_id: str,
    expected: str,
) -> None:
    async with hub_client(clean_database.url) as client:
        response = await _send(client, signal_payload(**payload_changes), agent_id=agent_id)
    assert response.status_code == 403
    assert reason_code(response) == expected


@pytest.mark.parametrize(
    ("snapshot_id", "analysis_timestamp", "expected"),
    [
        (str(UNKNOWN_SNAPSHOT_ID), NOW.isoformat(), "UNKNOWN_SNAPSHOT"),
        (str(EXPIRED_SNAPSHOT_ID), NOW.isoformat(), "SNAPSHOT_NOT_OPEN"),
        (str(INVALID_SNAPSHOT_ID), NOW.isoformat(), "SNAPSHOT_NOT_OPEN"),
        (
            str(INCOMPATIBLE_SNAPSHOT_ID),
            (NOW - timedelta(seconds=20)).isoformat(),
            "SIGNAL_SNAPSHOT_TIME_MISMATCH",
        ),
    ],
)
async def test_snapshot_matrix(
    clean_database: DatabaseHarness,
    snapshot_id: str,
    analysis_timestamp: str,
    expected: str,
) -> None:
    payload = signal_payload(
        snapshot_id=snapshot_id,
        data_timestamp=analysis_timestamp,
        analysis_timestamp=analysis_timestamp,
    )
    async with hub_client(clean_database.url) as client:
        response = await _send(client, payload)
    assert response.status_code == 422
    assert reason_code(response) == expected


def _missing_field() -> dict[str, Any]:
    payload = signal_payload()
    del payload["confidence"]
    return payload


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (signal_payload(confidence=101), "INVALID_SCHEMA"),
        (signal_payload(bias="BUY_NOW"), "INVALID_SCHEMA"),
        (_missing_field(), "INVALID_SCHEMA"),
        (signal_payload(signal_ttl_seconds=0), "INVALID_SCHEMA"),
        (signal_payload(signal_ttl_seconds=301), "SIGNAL_TTL_EXCEEDS_MAXIMUM"),
        (
            signal_payload(
                analysis_timestamp=(NOW - timedelta(seconds=31)).isoformat(),
                data_timestamp=(NOW - timedelta(seconds=31)).isoformat(),
            ),
            "SIGNAL_EXPIRED",
        ),
        (
            signal_payload(
                evidence=[
                    {
                        "evidence_type": "test",
                        "summary": "x",
                        "source_type": "fixture",
                        "source_id": str(index),
                        "observed_at": NOW.isoformat(),
                        "source_timestamp": NOW.isoformat(),
                    }
                    for index in range(21)
                ]
            ),
            "INVALID_SCHEMA",
        ),
        (signal_payload(metadata={"oversized": "x" * 2_001}), "INVALID_SCHEMA"),
    ],
)
async def test_schema_and_freshness_matrix(
    clean_database: DatabaseHarness, payload: dict[str, Any], expected: str
) -> None:
    async with hub_client(clean_database.url) as client:
        response = await _send(client, payload)
    assert response.status_code == 422
    assert reason_code(response) == expected


async def test_oversized_request_is_rejected_before_parsing(
    clean_database: DatabaseHarness,
) -> None:
    body = b"{" + (b'"padding":"' + b"x" * 2_000 + b'"}')
    async with hub_client(clean_database.url, max_signal_request_bytes=1_024) as client:
        response = await client.post("/v1/signals", content=body, headers=signed_headers(body))
    assert response.status_code == 413
    assert reason_code(response) == "REQUEST_TOO_LARGE"


async def test_replay_and_duplicate_message_are_database_enforced(
    clean_database: DatabaseHarness,
) -> None:
    payload = signal_payload()
    body = encode_payload(payload)
    same_headers = signed_headers(body, nonce="fixed_nonce_value_1234567890")
    async with hub_client(clean_database.url) as client:
        accepted = await client.post("/v1/signals", content=body, headers=same_headers)
        replay = await client.post("/v1/signals", content=body, headers=same_headers)
        duplicate_message = await client.post(
            "/v1/signals", content=body, headers=signed_headers(body)
        )
    assert accepted.status_code == 202
    assert replay.status_code == 409
    assert duplicate_message.status_code == 409
    async with clean_database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Signal)) == 1
        assert await session.scalar(select(func.count()).select_from(Nonce)) == 1
