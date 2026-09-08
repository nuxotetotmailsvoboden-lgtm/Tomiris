from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tomiris_common.validation import validate_bounded_json


class AgentRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    enabled: bool
    protocol_version: str = Field(pattern=r"^1\.0$")
    criticality: str = Field(default="NORMAL", pattern=r"^(LOW|NORMAL|HIGH|CRITICAL)$")
    account_alias: str | None = Field(default=None, max_length=64)
    space_alias: str | None = Field(default=None, max_length=128)
    space_name: str | None = Field(default=None, max_length=128)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    supported_assets: list[str] = Field(default_factory=list, max_length=50)
    supported_evidence_types: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def bound_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_json(value)
