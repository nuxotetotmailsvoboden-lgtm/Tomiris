from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from tomiris_hub.database.models import AuditEvent


def add_orchestration_event(
    session: AsyncSession,
    *,
    now: datetime,
    event_type: str,
    correlation_id: UUID,
    causation_id: UUID | None,
    run_id: UUID,
    task_id: UUID | None = None,
    agent_id: str | None = None,
    snapshot_id: UUID | None = None,
    outcome: str = "ACCEPTED",
    reason_code: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    event_metadata: dict[str, object] = {"orchestration_run_id": str(run_id)}
    if task_id is not None:
        event_metadata["task_id"] = str(task_id)
    if metadata:
        event_metadata.update(metadata)
    session.add(
        AuditEvent(
            event_id=uuid4(),
            occurred_at=now,
            event_type=event_type,
            outcome=outcome,
            reason_code=reason_code,
            request_id=uuid4(),
            agent_id=agent_id,
            message_id=None,
            snapshot_id=snapshot_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload_hash=None,
            metadata_json=event_metadata,
        )
    )
