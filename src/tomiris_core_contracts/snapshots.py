from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_common.validation import validate_bounded_json


class SnapshotStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: UUID
    created_at: datetime
    expires_at: datetime
    status: SnapshotStatus
    context_version: Annotated[str, Field(min_length=1, max_length=32)]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at", "expires_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("snapshot timestamp must be UTC")
        return value

    @field_validator("metadata")
    @classmethod
    def bound_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_json(value)

    @model_validator(mode="after")
    def validate_window(self) -> MarketSnapshot:
        if self.expires_at <= self.created_at:
            raise ValueError("snapshot expiry must be after creation")
        return self
