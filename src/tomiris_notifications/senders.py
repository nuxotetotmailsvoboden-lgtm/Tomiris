from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from tomiris_core_contracts.notifications import NotificationEvent

logger = logging.getLogger(__name__)


class _SecretRedactionFilter(logging.Filter):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        def redact(value: object) -> object:
            rendered = str(value)
            return (
                rendered.replace(self._secret, "<redacted>") if self._secret in rendered else value
            )

        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        record.msg = redact(record.msg)
        return True


@dataclass(frozen=True)
class SendResult:
    success: bool
    retryable: bool = False
    error_code: str | None = None


class NotificationSender(Protocol):
    async def send(self, event: NotificationEvent) -> SendResult: ...


class NullNotificationSender:
    async def send(self, event: NotificationEvent) -> SendResult:
        del event
        return SendResult(success=True)


class ConsoleNotificationSender:
    async def send(self, event: NotificationEvent) -> SendResult:
        logger.info(
            "notification_console_send",
            extra={"notification_id": str(event.notification_id), "event_type": event.event_type},
        )
        return SendResult(success=True)


class TelegramNotificationSender:
    """Outbound-only Telegram transport with sanitized failure results."""

    def __init__(
        self,
        token: str,
        client: httpx.AsyncClient,
        api_base: str = "https://api.telegram.org",
    ) -> None:
        if not token:
            raise ValueError("Telegram token is required")
        self._token = token
        self._client = client
        self._api_base = api_base.rstrip("/")
        redactor = _SecretRedactionFilter(token)
        logging.getLogger("httpx").addFilter(redactor)
        logging.getLogger("httpcore").addFilter(redactor)

    async def send(self, event: NotificationEvent) -> SendResult:
        text = str(
            event.payload.get("text", "TOMIRIS SYSTEM TEST\nNotification Gateway operational.")
        )
        url = f"{self._api_base}/bot{self._token}/sendMessage"
        try:
            response = await self._client.post(
                url,
                json={"chat_id": event.recipient_ref, "text": text},
            )
        except httpx.TimeoutException:
            return SendResult(False, True, "TELEGRAM_TIMEOUT")
        except httpx.NetworkError:
            return SendResult(False, True, "TELEGRAM_NETWORK_ERROR")
        if 200 <= response.status_code < 300:
            return SendResult(True)
        if response.status_code == 429 or response.status_code >= 500:
            return SendResult(False, True, f"TELEGRAM_HTTP_{response.status_code}")
        return SendResult(False, False, f"TELEGRAM_HTTP_{response.status_code}")
