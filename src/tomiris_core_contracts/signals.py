from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tomiris_common.validation import validate_bounded_json

MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_SUMMARY = 1_000


def _require_utc(value: datetime) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError("timestamp must be timezone-aware")
    if offset.total_seconds() != 0:
        raise ValueError("timestamp must be UTC")
    return value


class Bias(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"
    ABSTAIN = "ABSTAIN"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_type: Annotated[str, Field(min_length=1, max_length=64)]
    summary: Annotated[str, Field(min_length=1, max_length=MAX_EVIDENCE_SUMMARY)]
    source_type: Annotated[str, Field(min_length=1, max_length=64)]
    source_id: Annotated[str, Field(min_length=1, max_length=256)]
    provider: Annotated[str, Field(min_length=1, max_length=128)] = "unknown"
    observed_at: datetime
    source_timestamp: datetime
    source_fingerprint: Annotated[str | None, Field(max_length=128)] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _utc = field_validator("observed_at", "source_timestamp")(_require_utc)

    @field_validator("metadata")
    @classmethod
    def bound_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_json(value)


class SignalEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Annotated[str, Field(pattern=r"^1\.0$")]
    message_id: UUID
    agent_id: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    agent_run_id: UUID
    snapshot_id: UUID
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    asset: Annotated[str, Field(pattern=r"^[A-Z0-9_./-]{2,32}$")]
    bias: Bias
    confidence: Annotated[int, Field(ge=0, le=100)]
    impact: Annotated[int, Field(ge=0, le=100)]
    time_horizon: Annotated[str, Field(min_length=1, max_length=64)]
    evidence: Annotated[list[EvidenceItem], Field(max_length=MAX_EVIDENCE_ITEMS)]
    risk_flags: Annotated[list[Annotated[str, Field(max_length=128)]], Field(max_length=20)] = (
        Field(default_factory=list)
    )
    data_timestamp: datetime
    analysis_timestamp: datetime
    signal_ttl_seconds: Annotated[int, Field(gt=0)]
    metadata: dict[str, Any] = Field(default_factory=dict)

    _utc = field_validator("data_timestamp", "analysis_timestamp")(_require_utc)

    @field_validator("metadata")
    @classmethod
    def bound_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_json(value)


AgentSignal = SignalEnvelope
