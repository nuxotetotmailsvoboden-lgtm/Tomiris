from __future__ import annotations

from tomiris_agent_roles.models import AgentDefinition
from tomiris_agent_roles.technical_role import ConfiguredTechnicalRole


class BTCContextRolePlugin:
    role_id = "btc.market_context.v1"
    role_version = "1.0.0"
    role_api_version = "1"

    def build(self, definition: AgentDefinition) -> ConfiguredTechnicalRole:
        if definition.role_id != self.role_id or definition.supported_assets != ("BTCUSDT",):
            raise ValueError("BTC context role requires exactly BTCUSDT")
        return ConfiguredTechnicalRole(
            definition,
            role_version=self.role_version,
            evidence_type="market_context",
        )
