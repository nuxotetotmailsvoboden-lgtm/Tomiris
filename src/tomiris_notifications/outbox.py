from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tomiris_core_contracts.notifications import NotificationEvent
from tomiris_hub.database.models import NotificationOutbox


async def enqueue_notification(session: AsyncSession, event: NotificationEvent) -> bool:
    """Insert once inside the caller's transaction."""

    statement = (
        insert(NotificationOutbox)
        .values(
            notification_id=event.notification_id,
            event_id=event.event_id,
            event_type=event.event_type,
            snapshot_id=event.snapshot_id,
            channel=event.channel,
            recipient_ref=event.recipient_ref,
            payload_json=event.payload,
            status="PENDING",
            attempt_count=0,
            next_attempt_at=event.created_at,
            last_error_code=None,
            created_at=event.created_at,
            sent_at=None,
            idempotency_key=event.idempotency_key,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
        )
        .on_conflict_do_nothing(index_elements=[NotificationOutbox.idempotency_key])
        .returning(NotificationOutbox.notification_id)
    )
    return (await session.scalar(statement)) is not None
