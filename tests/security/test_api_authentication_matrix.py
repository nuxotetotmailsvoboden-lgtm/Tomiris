from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from sqlalchemy import select
from tests.conftest import DatabaseHarness
from tests.support import (
    NOW,
    encode_payload,
    hub_client,
    reason_code,
    signal_payload,
    signed_headers,
)

from tomiris_hub.database.models import AuditEvent


async def _post_case(
    client: httpx.AsyncClient,
    *,
    header_change: Callable[[dict[str, str]], None] | None = None,
    signed_body: bytes | None = None,
    sent_body: bytes | None = None,
    secret: str | None = None,
    key_id: str = "current",
    agent_id: str = "TEST_AGENT_001",
) -> httpx.Response:
    body = signed_body or encode_payload(signal_payload())
    headers = signed_headers(
        body,
        secret=secret or "0123456789abcdef0123456789abcdef",
        key_id=key_id,
        agent_id=agent_id,
    )
    if header_change:
        header_change(headers)
    return await client.post("/v1/signals", content=sent_body or body, headers=headers)


@pytest.mark.parametrize(
    ("header_name", "expected"),
    [
        ("X-Tomiris-Signature", "MISSING_AUTH_HEADERS"),
        ("X-Tomiris-Timestamp", "MISSING_AUTH_HEADERS"),
        ("X-Tomiris-Nonce", "MISSING_AUTH_HEADERS"),
    ],
)
async def test_missing_auth_headers_are_controlled(
    clean_database: DatabaseHarness, header_name: str, expected: str
) -> None:
    async with hub_client(clean_database.url) as client:
        response = await _post_case(client, header_change=lambda h: h.pop(header_name))
    assert response.status_code == 401
    assert reason_code(response) == expected


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda h: h.update({"X-Tomiris-Timestamp": "not-a-time"}), "INVALID_TIMESTAMP"),
        (lambda h: h.update({"X-Tomiris-Signature": "xyz"}), "MALFORMED_SIGNATURE"),
        (
            lambda h: h.update({"X-Tomiris-Timestamp": str(int(NOW.timestamp()) - 61)}),
            "AUTH_TIMESTAMP_TOO_OLD",
        ),
        (
            lambda h: h.update({"X-Tomiris-Timestamp": str(int(NOW.timestamp()) + 61)}),
            "AUTH_TIMESTAMP_IN_FUTURE",
        ),
    ],
)
async def test_malformed_and_stale_auth_is_controlled(
    clean_database: DatabaseHarness,
    change: Callable[[dict[str, str]], None],
    expected: str,
) -> None:
    async with hub_client(clean_database.url) as client:
        response = await _post_case(client, header_change=change)
    assert response.status_code == 401
    assert reason_code(response) == expected


async def test_hmac_integrity_matrix(clean_database: DatabaseHarness) -> None:
    async with hub_client(clean_database.url) as client:
        valid = await _post_case(client)
        wrong_secret = await _post_case(client, secret="f" * 32)
        unknown_key = await _post_case(client, key_id="unknown")
        original = encode_payload(signal_payload())
        changed_body = original.replace(b'"confidence":70', b'"confidence":71')
        changed_raw = await _post_case(client, signed_body=original, sent_body=changed_body)
        changed_agent = await _post_case(
            client,
            header_change=lambda h: h.update({"X-Tomiris-Agent-ID": "OTHER_AGENT_001"}),
        )
    assert valid.status_code == 202
    assert (wrong_secret.status_code, reason_code(wrong_secret)) == (401, "INVALID_SIGNATURE")
    assert (unknown_key.status_code, reason_code(unknown_key)) == (401, "UNKNOWN_KEY_ID")
    assert (changed_raw.status_code, reason_code(changed_raw)) == (401, "INVALID_SIGNATURE")
    assert (changed_agent.status_code, reason_code(changed_agent)) == (401, "INVALID_SIGNATURE")


async def test_rejected_security_request_is_durably_audited(
    clean_database: DatabaseHarness,
) -> None:
    async with hub_client(clean_database.url) as client:
        response = await _post_case(client, secret="f" * 32)
    assert response.status_code == 401
    async with clean_database.session_factory() as session:
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.reason_code == "INVALID_SIGNATURE")
        )
    assert audit is not None
    assert audit.outcome == "REJECTED" and audit.payload_hash is not None
