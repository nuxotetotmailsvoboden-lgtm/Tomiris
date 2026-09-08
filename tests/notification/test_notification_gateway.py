from __future__ import annotations

import logging
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from tests.conftest import DatabaseHarness
from tests.support import NOW, encode_payload, hub_client, signal_payload, signed_headers

from tomiris_core_contracts.notifications import NotificationEvent
from tomiris_hub.core.clock import FakeClock
from tomiris_hub.database.models import NotificationOutbox, Signal
from tomiris_notifications.outbox import enqueue_notification
from tomiris_notifications.senders import (
    ConsoleNotificationSender,
    NullNotificationSender,
    TelegramNotificationSender,
)
from tomiris_notifications.worker import NotificationWorker

TOKEN = "123456:SECRET_TOKEN_MUST_NEVER_BE_LOGGED"  # noqa: S105 - mock token


def _event(idempotency_key: str = "system-test:1") -> NotificationEvent:
    event_id = uuid4()
    return NotificationEvent(
        notification_id=uuid4(),
        event_id=event_id,
        event_type="TOMIRIS_SYSTEM_TEST",
        snapshot_id=None,
        channel="telegram",
        recipient_ref="12345",
        payload={"text": "TOMIRIS SYSTEM TEST\nNotification Gateway operational."},
        idempotency_key=idempotency_key,
        correlation_id=event_id,
        causation_id=None,
        created_at=NOW,
    )


async def _sender_with_status(status: int) -> tuple[TelegramNotificationSender, httpx.AsyncClient]:
    transport = httpx.MockTransport(lambda _: httpx.Response(status, json={"ok": status < 300}))
    client = httpx.AsyncClient(transport=transport)
    return TelegramNotificationSender(TOKEN, client), client


async def _queued(clean_database: DatabaseHarness, event: NotificationEvent) -> None:
    async with clean_database.session_factory() as session, session.begin():
        assert await enqueue_notification(session, event)


def _worker(
    clean_database: DatabaseHarness,
    sender: TelegramNotificationSender,
    clock: FakeClock,
    *,
    attempts: int = 3,
) -> NotificationWorker:
    return NotificationWorker(
        clean_database.session_factory,
        sender,
        clock,
        max_attempts=attempts,
        base_retry_seconds=1,
        max_retry_seconds=4,
        sending_lease_seconds=10,
        jitter=lambda: 0.0,
    )


async def test_successful_telegram_mock_marks_sent(clean_database: DatabaseHarness) -> None:
    event = _event()
    await _queued(clean_database, event)
    sender, http_client = await _sender_with_status(200)
    try:
        assert await _worker(clean_database, sender, FakeClock(NOW)).process_one()
    finally:
        await http_client.aclose()
    async with clean_database.session_factory() as session:
        row = await session.get(NotificationOutbox, event.notification_id)
    assert row is not None and row.status == "SENT"
    assert row.attempt_count == 1 and row.sent_at == NOW


async def test_null_and_console_adapters_are_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = _event()
    caplog.set_level(logging.INFO)
    assert (await NullNotificationSender().send(event)).success
    assert (await ConsoleNotificationSender().send(event)).success
    assert caplog.records[-1].notification_id == str(event.notification_id)


async def test_timeout_is_retryable(clean_database: DatabaseHarness) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("system-test timeout", request=request)

    event = _event()
    await _queued(clean_database, event)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    sender = TelegramNotificationSender(TOKEN, http_client)
    try:
        await _worker(clean_database, sender, FakeClock(NOW)).process_one()
    finally:
        await http_client.aclose()
    async with clean_database.session_factory() as session:
        row = await session.get(NotificationOutbox, event.notification_id)
    assert row is not None and row.status == "RETRY"
    assert row.last_error_code == "TELEGRAM_TIMEOUT"


async def test_telegram_5xx_retries_then_dead_letters(
    clean_database: DatabaseHarness,
) -> None:
    event = _event()
    await _queued(clean_database, event)
    sender, http_client = await _sender_with_status(503)
    clock = FakeClock(NOW)
    worker = _worker(clean_database, sender, clock, attempts=2)
    try:
        await worker.process_one()
        clock.advance_seconds(1)
        await worker.process_one()
    finally:
        await http_client.aclose()
    async with clean_database.session_factory() as session:
        row = await session.get(NotificationOutbox, event.notification_id)
    assert row is not None and row.status == "DEAD_LETTER"
    assert row.attempt_count == 2
    assert row.last_error_code == "TELEGRAM_HTTP_503"


async def test_permanent_telegram_failure_does_not_retry(
    clean_database: DatabaseHarness,
) -> None:
    event = _event()
    await _queued(clean_database, event)
    sender, http_client = await _sender_with_status(400)
    try:
        await _worker(clean_database, sender, FakeClock(NOW)).process_one()
    finally:
        await http_client.aclose()
    async with clean_database.session_factory() as session:
        row = await session.get(NotificationOutbox, event.notification_id)
    assert row is not None and row.status == "FAILED"
    assert row.attempt_count == 1


async def test_duplicate_notification_idempotency_key_is_ignored(
    clean_database: DatabaseHarness,
) -> None:
    first = _event("same-business-event")
    second = _event("same-business-event")
    async with clean_database.session_factory() as session, session.begin():
        inserted_first = await enqueue_notification(session, first)
        inserted_second = await enqueue_notification(session, second)
    assert inserted_first is True
    assert inserted_second is False
    async with clean_database.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(NotificationOutbox))
    assert count == 1


async def test_token_absent_from_logs_on_failure(
    clean_database: DatabaseHarness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    event = _event()
    await _queued(clean_database, event)
    sender, http_client = await _sender_with_status(500)
    try:
        await _worker(clean_database, sender, FakeClock(NOW)).process_one()
    finally:
        await http_client.aclose()
    assert TOKEN not in caplog.text


async def test_notification_failure_cannot_corrupt_accepted_signal(
    clean_database: DatabaseHarness,
) -> None:
    body = encode_payload(signal_payload())
    async with hub_client(clean_database.url) as client:
        accepted = await client.post("/v1/signals", content=body, headers=signed_headers(body))
    assert accepted.status_code == 202

    event = _event()
    await _queued(clean_database, event)
    sender, http_client = await _sender_with_status(400)
    try:
        await _worker(clean_database, sender, FakeClock(NOW)).process_one()
    finally:
        await http_client.aclose()
    async with clean_database.session_factory() as session:
        signal_count = await session.scalar(select(func.count()).select_from(Signal))
        row = await session.get(NotificationOutbox, event.notification_id)
    assert signal_count == 1
    assert row is not None and row.status == "FAILED"
