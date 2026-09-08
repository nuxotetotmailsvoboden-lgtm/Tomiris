from __future__ import annotations

from tomiris_agent_roles.models import AgentAnalysisResult, AgentDefinition, RoleInput
from tomiris_agent_roles.technical import TechnicalAnalysisEngine, TechnicalRoleConfig


class ConfiguredTechnicalRole:
    feature_pipeline_version = "technical-pipeline.v1"
    analysis_schema_version = "1"

    def __init__(
        self,
        definition: AgentDefinition,
        *,
        role_version: str,
        evidence_type: str,
    ) -> None:
        self.definition = definition
        self.role_id = definition.role_id
        self.role_version = role_version
        self.config = TechnicalRoleConfig.model_validate(definition.parameters)
        self.engine = TechnicalAnalysisEngine(self.config, evidence_type=evidence_type)

    def analyze(self, role_input: RoleInput) -> AgentAnalysisResult:
        return self.engine.analyze(
            self.definition,
            role_input,
            role_version=self.role_version,
        )
