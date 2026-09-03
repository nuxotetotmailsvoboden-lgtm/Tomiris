from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from sqlalchemy.dialects.postgresql import insert

from tomiris_hub.core.config import get_settings
from tomiris_hub.database.models import Agent
from tomiris_hub.database.session import build_engine, build_session_factory
from tomiris_hub.schemas.agents import AgentRegistryEntry


async def main() -> None:
    registry = yaml.safe_load(Path("agents/registry.yaml").read_text(encoding="utf-8"))
    entries = [AgentRegistryEntry.model_validate(item) for item in registry["agents"]]
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    async with factory() as session, session.begin():
        for item in entries:
            values = {
                "agent_id": item.agent_id,
                "name": item.name,
                "role": item.role,
                "enabled": item.enabled,
                "protocol_version": item.protocol_version,
                "metadata_json": {
                    "account_alias": item.account_alias,
                    "space_name": item.space_name,
                    "capabilities": item.capabilities,
                },
            }
            statement = (
                insert(Agent)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[Agent.agent_id],
                    set_={key: value for key, value in values.items() if key != "agent_id"},
                )
            )
            await session.execute(statement)
    await engine.dispose()
    print(f"Synced {len(entries)} agent(s).")


if __name__ == "__main__":
    asyncio.run(main())
