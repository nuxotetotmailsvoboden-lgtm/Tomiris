from __future__ import annotations

from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tomiris_core_contracts.orchestration import RuntimeCapabilities
from tomiris_hub.core.clock import Clock
from tomiris_hub.database.models import Agent, AgentEndpoint, AgentRuntimeState
from tomiris_orchestrator.endpoint_security import EndpointValidator
from tomiris_orchestrator.errors import EndpointSecurityError


class AgentHealthProber:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        endpoint_validator: EndpointValidator,
        *,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.endpoint_validator = endpoint_validator
        self.timeout_seconds = timeout_seconds
        self.http_client = http_client

    async def probe_enabled(self) -> int:
        async with self.session_factory() as session:
            agent_ids = list(
                (
                    await session.scalars(
                        select(Agent.agent_id)
                        .join(AgentEndpoint, AgentEndpoint.agent_id == Agent.agent_id)
                        .where(Agent.enabled.is_(True), AgentEndpoint.enabled.is_(True))
                    )
                ).all()
            )
        for agent_id in agent_ids:
            await self.probe(agent_id)
        return len(agent_ids)

    async def probe(self, agent_id: str) -> str:
        async with self.session_factory() as session:
            agent = await session.get(Agent, agent_id)
            endpoint = await session.get(AgentEndpoint, agent_id)
        now = self.clock.now()
        availability = "UNAVAILABLE"
        error_code: str | None = None
        latency_ms: float | None = None
        if agent is None or endpoint is None or not endpoint.enabled:
            error_code = "AGENT_ENDPOINT_MISSING"
        else:
            started = datetime.now().timestamp()
            try:
                origin = await self.endpoint_validator.validate(
                    endpoint.endpoint_url, endpoint.environment
                )
                owns_client = self.http_client is None
                client = self.http_client or httpx.AsyncClient(timeout=self.timeout_seconds)
                try:
                    live = await client.get(f"{origin}/health/live")
                    ready = await client.get(f"{origin}/health/ready")
                    capabilities_response = await client.get(f"{origin}/v1/capabilities")
                finally:
                    if owns_client:
                        await client.aclose()
                latency_ms = max(0.0, (datetime.now().timestamp() - started) * 1000)
                if live.status_code != 200 or ready.status_code != 200:
                    error_code = "AGENT_UNAVAILABLE"
                elif capabilities_response.status_code != 200:
                    error_code = "AGENT_CAPABILITY_MISMATCH"
                    availability = "DEGRADED"
                else:
                    runtime = RuntimeCapabilities.model_validate(capabilities_response.json())
                    drift = (
                        runtime.agent_id != agent.agent_id
                        or runtime.role != agent.role
                        or set(runtime.capabilities) != set(agent.capabilities)
                        or set(runtime.supported_assets) != set(agent.supported_assets)
                        or agent.protocol_version not in runtime.protocol_versions
                    )
                    availability = "DEGRADED" if drift else "HEALTHY"
                    error_code = "AGENT_CAPABILITY_MISMATCH" if drift else None
            except EndpointSecurityError as error:
                error_code = error.code
            except (httpx.HTTPError, ValueError, TypeError):
                error_code = "AGENT_UNAVAILABLE"
        async with self.session_factory() as session, session.begin():
            state = await session.get(AgentRuntimeState, agent_id, with_for_update=True)
            if state is None:
                state = AgentRuntimeState(
                    agent_id=agent_id,
                    availability=availability,
                    consecutive_failures=0,
                    circuit_state="CLOSED",
                    updated_at=now,
                )
                session.add(state)
            state.availability = availability
            state.last_probe_at = now
            state.last_seen_at = (
                now if availability in {"HEALTHY", "DEGRADED"} else state.last_seen_at
            )
            state.latency_ms = latency_ms
            state.last_error_code = error_code
            state.updated_at = now
        return availability
