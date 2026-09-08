from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    instrument: Annotated[str | None, Field(max_length=32)] = None
    timeframe: Annotated[str | None, Field(max_length=16)] = None
    feature_name: Annotated[str | None, Field(max_length=64)] = None
    feature_version: Annotated[str | None, Field(max_length=32)] = None
    observation: Annotated[str | None, Field(max_length=500)] = None
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
    task_id: UUID | None = None
    orchestration_run_id: UUID | None = None
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
    role_id: Annotated[str | None, Field(max_length=64)] = None
    role_version: Annotated[str | None, Field(max_length=32)] = None
    config_version: Annotated[str | None, Field(max_length=32)] = None
    feature_pipeline_version: Annotated[str | None, Field(max_length=64)] = None
    analysis_schema_version: Annotated[str | None, Field(max_length=16)] = None
    data_provider: Annotated[str | None, Field(max_length=128)] = None
    data_as_of: datetime | None = None
    confidence_model_version: Annotated[str | None, Field(max_length=32)] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _utc = field_validator("data_timestamp", "analysis_timestamp")(_require_utc)

    @field_validator("data_as_of")
    @classmethod
    def optional_utc(cls, value: datetime | None) -> datetime | None:
        return _require_utc(value) if value is not None else None

    @field_validator("metadata")
    @classmethod
    def bound_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_json(value)

    @model_validator(mode="after")
    def validate_task_lineage(self) -> SignalEnvelope:
        if (self.task_id is None) != (self.orchestration_run_id is None):
            raise ValueError("task_id and orchestration_run_id must be provided together")
        analytical = (
            self.role_id,
            self.role_version,
            self.config_version,
            self.feature_pipeline_version,
            self.analysis_schema_version,
            self.data_provider,
            self.data_as_of,
            self.confidence_model_version,
        )
        if any(value is not None for value in analytical) and any(
            value is None for value in analytical
        ):
            raise ValueError("analytical lineage fields must be provided together")
        if self.data_as_of is not None and self.data_as_of > self.analysis_timestamp:
            raise ValueError("data_as_of cannot be after analysis_timestamp")
        return self


AgentSignal = SignalEnvelope
