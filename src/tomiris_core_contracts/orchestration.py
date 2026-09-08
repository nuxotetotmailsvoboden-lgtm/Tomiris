from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_common.validation import validate_bounded_json


def _require_utc(value: datetime) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("timestamp must be UTC")
    return value


class TaskAckStatus(StrEnum):
    ACKNOWLEDGED = "ACKNOWLEDGED"


class AnalysisTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: Annotated[str, Field(pattern=r"^1\.0$")]
    task_id: UUID
    orchestration_run_id: UUID
    snapshot_id: UUID
    agent_id: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    asset: Annotated[str, Field(pattern=r"^[A-Z0-9_./-]{2,32}$")]
    required_capability: Annotated[str, Field(min_length=1, max_length=64)]
    priority: Annotated[int, Field(ge=0, le=100)]
    created_at: datetime
    deadline: datetime
    correlation_id: UUID
    causation_id: UUID | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    _utc = field_validator("created_at", "deadline")(_require_utc)

    @field_validator("context")
    @classmethod
    def bound_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_json(
            value,
            max_depth=4,
            max_items=50,
            max_string_length=2_000,
        )

    @model_validator(mode="after")
    def validate_deadline(self) -> AnalysisTaskRequest:
        if self.deadline <= self.created_at:
            raise ValueError("deadline must be after created_at")
        return self


class AnalysisTaskAck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    agent_id: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    status: TaskAckStatus = TaskAckStatus.ACKNOWLEDGED
    accepted_at: datetime
    runtime_version: Annotated[str, Field(min_length=1, max_length=32)]

    _utc = field_validator("accepted_at")(_require_utc)


class RuntimeCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    runtime_version: Annotated[str, Field(min_length=1, max_length=32)]
    role: Annotated[str, Field(min_length=1, max_length=64)]
    capabilities: Annotated[list[str], Field(max_length=50)]
    supported_assets: Annotated[list[str], Field(max_length=100)]
    protocol_versions: Annotated[list[str], Field(min_length=1, max_length=10)]
    analytical_role_api_version: Annotated[str | None, Field(max_length=16)] = None


class CapabilityRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: Annotated[str, Field(min_length=1, max_length=64)]
    required: bool = True
    critical: bool = False
    minimum_responses: Annotated[int, Field(ge=1, le=500)] = 1
    max_agents: Annotated[int | None, Field(ge=1, le=500)] = None


class OrchestrationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_version: Annotated[str, Field(min_length=1, max_length=32)]
    requirements: Annotated[list[CapabilityRequirement], Field(min_length=1, max_length=100)]
    collection_timeout_seconds: Annotated[int, Field(ge=1, le=86_400)]
    dispatch_timeout_seconds: Annotated[int, Field(ge=1, le=3_600)]
    signal_timeout_seconds: Annotated[int, Field(ge=1, le=86_400)]

    @model_validator(mode="after")
    def unique_capabilities(self) -> OrchestrationPolicy:
        names = [item.capability for item in self.requirements]
        if len(names) != len(set(names)):
            raise ValueError("policy capabilities must be unique")
        if self.signal_timeout_seconds < self.dispatch_timeout_seconds:
            raise ValueError("signal timeout must be >= dispatch timeout")
        if self.collection_timeout_seconds < self.signal_timeout_seconds:
            raise ValueError("collection timeout must be >= signal timeout")
        return self
