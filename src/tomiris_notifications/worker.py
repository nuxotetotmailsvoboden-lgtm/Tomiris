from __future__ import annotations

import random
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tomiris_core_contracts.notifications import NotificationEvent
from tomiris_hub.core.clock import Clock
from tomiris_hub.database.models import NotificationOutbox
from tomiris_notifications.senders import NotificationSender


def exponential_backoff_seconds(
    attempt: int,
    base_seconds: int,
    maximum_seconds: int,
    jitter: Callable[[], float] = random.random,
) -> float:
    bounded = min(maximum_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    return float(bounded * (1 + 0.2 * min(1.0, max(0.0, jitter()))))


class NotificationWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        sender: NotificationSender,
        clock: Clock,
        *,
        max_attempts: int,
        base_retry_seconds: int,
        max_retry_seconds: int,
        sending_lease_seconds: int = 60,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.session_factory = session_factory
        self.sender = sender
        self.clock = clock
        self.max_attempts = max_attempts
        self.base_retry_seconds = base_retry_seconds
        self.max_retry_seconds = max_retry_seconds
        self.sending_lease_seconds = sending_lease_seconds
        self.jitter = jitter

    async def process_one(self) -> bool:
        async with self.session_factory() as session, session.begin():
            row = await session.scalar(
                select(NotificationOutbox)
                .where(
                    or_(
                        NotificationOutbox.status.in_(("PENDING", "RETRY")),
                        NotificationOutbox.status == "SENDING",
                    ),
                    NotificationOutbox.next_attempt_at <= self.clock.now(),
                )
                .order_by(NotificationOutbox.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return False
            row.status = "SENDING"
            row.attempt_count += 1
            row.next_attempt_at = self.clock.now() + timedelta(seconds=self.sending_lease_seconds)
            event = NotificationEvent(
                notification_id=row.notification_id,
                event_id=row.event_id,
                event_type=row.event_type,
                snapshot_id=row.snapshot_id,
                channel=row.channel,
                recipient_ref=row.recipient_ref,
                payload=row.payload_json,
                idempotency_key=row.idempotency_key,
                correlation_id=row.correlation_id,
                causation_id=row.causation_id,
                created_at=row.created_at,
            )
            notification_id = row.notification_id
            attempt_count = row.attempt_count

        result = await self.sender.send(event)

        async with self.session_factory() as session, session.begin():
            row = await session.get(
                NotificationOutbox,
                notification_id,
                with_for_update=True,
            )
            if row is None or row.status != "SENDING":
                return True
            if result.success:
                row.status = "SENT"
                row.sent_at = self.clock.now()
                row.last_error_code = None
            elif not result.retryable:
                row.status = "FAILED"
                row.last_error_code = result.error_code
            elif attempt_count >= self.max_attempts:
                row.status = "DEAD_LETTER"
                row.last_error_code = result.error_code
            else:
                delay = exponential_backoff_seconds(
                    attempt_count,
                    self.base_retry_seconds,
                    self.max_retry_seconds,
                    self.jitter,
                )
                row.status = "RETRY"
                row.next_attempt_at = self.clock.now() + timedelta(seconds=delay)
                row.last_error_code = result.error_code
        return True
