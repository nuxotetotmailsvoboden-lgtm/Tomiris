from __future__ import annotations

import asyncio
import os
from uuid import uuid4

from tomiris_core_contracts.notifications import NotificationEvent
from tomiris_hub.core.clock import SystemClock
from tomiris_hub.core.config import get_settings
from tomiris_hub.database.session import build_engine, build_session_factory
from tomiris_notifications.outbox import enqueue_notification


async def main() -> None:
    settings = get_settings()
    recipient = settings.telegram_chat_id or os.getenv("TOMIRIS_TEST_RECIPIENT", "console")
    clock = SystemClock()
    event_id = uuid4()
    event = NotificationEvent(
        notification_id=uuid4(),
        event_id=event_id,
        event_type="TOMIRIS_SYSTEM_TEST",
        snapshot_id=None,
        channel="telegram" if settings.telegram_enabled else "console",
        recipient_ref=recipient,
        payload={"text": "TOMIRIS SYSTEM TEST\nNotification Gateway operational."},
        idempotency_key=f"tomiris-system-test:{event_id}",
        correlation_id=event_id,
        causation_id=None,
        created_at=clock.now(),
    )
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    async with factory() as session, session.begin():
        inserted = await enqueue_notification(session, event)
    await engine.dispose()
    print(f"queued={inserted} notification_id={event.notification_id}")


if __name__ == "__main__":
    asyncio.run(main())
