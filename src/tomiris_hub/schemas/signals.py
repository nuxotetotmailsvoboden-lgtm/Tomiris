from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_SUMMARY = 1000


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
    observed_at: datetime
    source_timestamp: datetime
    source_fingerprint: Annotated[str | None, Field(max_length=128)] = None
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=20)

    @field_validator("observed_at", "source_timestamp")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware RFC3339 UTC")
        return value


class SignalEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Annotated[str, Field(pattern=r"^1\.0$")]
    message_id: UUID
    agent_id: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    agent_run_id: UUID
    snapshot_id: UUID
    asset: Annotated[str, Field(pattern=r"^[A-Z0-9_./-]{2,32}$")]
    bias: Bias
    confidence: Annotated[int, Field(ge=0, le=100)]
    impact: Annotated[int, Field(ge=0, le=100)]
    time_horizon: Annotated[str, Field(min_length=1, max_length=64)]
    evidence: Annotated[list[EvidenceItem], Field(max_length=MAX_EVIDENCE_ITEMS)]
    risk_flags: Annotated[list[str], Field(max_length=20)] = Field(default_factory=list)
    data_timestamp: datetime
    analysis_timestamp: datetime
    signal_ttl_seconds: Annotated[int, Field(gt=0)]
    metadata: dict[str, Any] = Field(default_factory=dict, max_length=20)

    @field_validator("data_timestamp", "analysis_timestamp")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware RFC3339 UTC")
        return value
