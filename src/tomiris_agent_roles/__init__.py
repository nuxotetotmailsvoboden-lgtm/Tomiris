"""Versioned analytical role plugins used by the Universal Agent Runtime."""

from tomiris_agent_roles.builtin import create_builtin_role_registry
from tomiris_agent_roles.registry import ANALYTICAL_ROLE_API_VERSION, AgentRoleRegistry

__all__ = ["ANALYTICAL_ROLE_API_VERSION", "AgentRoleRegistry", "create_builtin_role_registry"]
