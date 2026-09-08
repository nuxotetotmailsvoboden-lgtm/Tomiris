from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tomiris_common.validation import validate_bounded_json


class NotificationEvent(BaseModel):
    """Outbound-only event; it carries no command or decision authority."""

    model_config = ConfigDict(extra="forbid")
    notification_id: UUID
    event_id: UUID
    event_type: Annotated[str, Field(min_length=1, max_length=64)]
    snapshot_id: UUID | None = None
    channel: Annotated[str, Field(min_length=1, max_length=32)]
    recipient_ref: Annotated[str, Field(min_length=1, max_length=256)]
    payload: dict[str, Any]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=256)]
    correlation_id: UUID
    causation_id: UUID | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise ValueError("created_at must be timezone-aware")
        if offset.total_seconds() != 0:
            raise ValueError("created_at must be UTC")
        return value

    @field_validator("payload")
    @classmethod
    def bound_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_json(value, max_depth=4, max_items=50, max_string_length=4_000)
