from __future__ import annotations

from typing import Protocol

from tomiris_agent_roles.models import AgentAnalysisResult, AgentDefinition, RoleInput


class AnalyticalRole(Protocol):
    role_id: str
    role_version: str
    feature_pipeline_version: str
    analysis_schema_version: str
    definition: AgentDefinition

    def analyze(self, role_input: RoleInput) -> AgentAnalysisResult: ...


class RolePlugin(Protocol):
    role_id: str
    role_version: str
    role_api_version: str

    def build(self, definition: AgentDefinition) -> AnalyticalRole: ...
