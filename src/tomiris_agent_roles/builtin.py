from __future__ import annotations

from tomiris_agent_roles.btc_context import BTCContextRolePlugin
from tomiris_agent_roles.eth_technical import ETHTechnicalRolePlugin
from tomiris_agent_roles.registry import AgentRoleRegistry
from tomiris_agent_roles.sol_technical import SOLTechnicalRolePlugin


def create_builtin_role_registry() -> AgentRoleRegistry:
    registry = AgentRoleRegistry()
    registry.register_many(
        (
            BTCContextRolePlugin(),
            ETHTechnicalRolePlugin(),
            SOLTechnicalRolePlugin(),
        )
    )
    return registry
