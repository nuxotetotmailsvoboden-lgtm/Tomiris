from __future__ import annotations

from pathlib import Path

import yaml

from tomiris_agent_roles.models import AgentDefinition
from tomiris_agent_roles.registry import AgentRoleRegistry


class AgentDefinitionLoader:
    def __init__(self, registry: AgentRoleRegistry) -> None:
        self.registry = registry

    def load_file(self, path: Path) -> AgentDefinition:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        definition = AgentDefinition.model_validate(payload)
        self.registry.build(definition)
        return definition

    def load_directory(self, path: Path) -> dict[str, AgentDefinition]:
        definitions: dict[str, AgentDefinition] = {}
        for source in sorted(path.glob("*.yaml")):
            definition = self.load_file(source)
            if definition.agent_id in definitions:
                raise ValueError(f"duplicate agent_id: {definition.agent_id}")
            definitions[definition.agent_id] = definition
        return definitions
