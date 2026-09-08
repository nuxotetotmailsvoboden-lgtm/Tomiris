from __future__ import annotations

from tomiris_agent_roles.models import AgentDefinition
from tomiris_agent_roles.technical_role import ConfiguredTechnicalRole


class ETHTechnicalRolePlugin:
    role_id = "eth.technical.v1"
    role_version = "1.0.0"
    role_api_version = "1"

    def build(self, definition: AgentDefinition) -> ConfiguredTechnicalRole:
        if definition.role_id != self.role_id or definition.supported_assets != ("ETHUSDT",):
            raise ValueError("ETH technical role requires exactly ETHUSDT")
        return ConfiguredTechnicalRole(
            definition,
            role_version=self.role_version,
            evidence_type="technical_feature",
        )
