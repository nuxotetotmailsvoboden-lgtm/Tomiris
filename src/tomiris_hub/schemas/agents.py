from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=64)
    enabled: bool
    protocol_version: str = Field(pattern=r"^1\.0$")
    account_alias: str | None = Field(default=None, max_length=64)
    space_name: str | None = Field(default=None, max_length=128)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
