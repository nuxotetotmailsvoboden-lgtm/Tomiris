from __future__ import annotations

from collections.abc import Iterable

from tomiris_agent_roles.base import AnalyticalRole, RolePlugin
from tomiris_agent_roles.models import AgentDefinition, RoleLifecycle

ANALYTICAL_ROLE_API_VERSION = "1"


class AgentRoleRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, RolePlugin] = {}

    def register(self, plugin: RolePlugin) -> None:
        if plugin.role_id in self._plugins:
            raise ValueError(f"duplicate analytical role: {plugin.role_id}")
        if plugin.role_api_version != ANALYTICAL_ROLE_API_VERSION:
            raise ValueError(
                f"role {plugin.role_id} uses unsupported API {plugin.role_api_version}"
            )
        self._plugins[plugin.role_id] = plugin

    def register_many(self, plugins: Iterable[RolePlugin]) -> None:
        for plugin in plugins:
            self.register(plugin)

    def build(self, definition: AgentDefinition) -> AnalyticalRole:
        plugin = self._plugins.get(definition.role_id)
        if plugin is None:
            raise ValueError(f"unknown analytical role: {definition.role_id}")
        if not definition.enabled or definition.lifecycle == RoleLifecycle.DISABLED:
            raise ValueError(f"analytical role is disabled: {definition.role_id}")
        return plugin.build(definition)

    def role_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))
