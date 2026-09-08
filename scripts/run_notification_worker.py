from __future__ import annotations

import asyncio

import httpx

from tomiris_hub.core.clock import SystemClock
from tomiris_hub.core.config import get_settings
from tomiris_hub.database.session import build_engine, build_session_factory
from tomiris_notifications.senders import (
    ConsoleNotificationSender,
    TelegramNotificationSender,
)
from tomiris_notifications.worker import NotificationWorker


async def main() -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    async with httpx.AsyncClient(timeout=10.0) as client:
        if settings.telegram_enabled:
            assert settings.telegram_bot_token is not None
            sender = TelegramNotificationSender(
                settings.telegram_bot_token.get_secret_value(), client
            )
        else:
            sender = ConsoleNotificationSender()
        worker = NotificationWorker(
            factory,
            sender,
            SystemClock(),
            max_attempts=settings.notification_max_attempts,
            base_retry_seconds=settings.notification_base_retry_seconds,
            max_retry_seconds=settings.notification_max_retry_seconds,
        )
        processed = await worker.process_one()
        print(f"processed={processed}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
