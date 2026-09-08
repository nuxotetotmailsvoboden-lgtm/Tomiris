from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tomiris_hub.database.models import Agent, AgentEndpoint


@dataclass(frozen=True)
class RoutedAgent:
    agent_id: str
    capability: str
    criticality: str
    endpoint_url: str
    environment: str


class CapabilityRouter:
    """The database registry is authoritative; runtime claims never grant permissions."""

    async def select(
        self,
        session: AsyncSession,
        *,
        asset: str,
        capability: str,
        limit: int | None = None,
    ) -> list[RoutedAgent]:
        rows = (
            await session.execute(
                select(Agent, AgentEndpoint)
                .join(AgentEndpoint, AgentEndpoint.agent_id == Agent.agent_id)
                .where(Agent.enabled.is_(True), AgentEndpoint.enabled.is_(True))
                .order_by(Agent.agent_id)
            )
        ).all()
        routed = [
            RoutedAgent(
                agent_id=agent.agent_id,
                capability=capability,
                criticality=agent.criticality,
                endpoint_url=endpoint.endpoint_url,
                environment=endpoint.environment,
            )
            for agent, endpoint in rows
            if capability in agent.capabilities and asset in agent.supported_assets
        ]
        return routed if limit is None else routed[:limit]
