from __future__ import annotations

import httpx
from tests.conftest import DatabaseHarness
from tests.integration.test_phase02_orchestration import add_endpoint
from tests.support import NOW

from tomiris_agent_runtime.application import create_agent_runtime_app
from tomiris_agent_runtime.config import AgentRuntimeSettings
from tomiris_agent_runtime.sink import NullSignalSink
from tomiris_hub.core.clock import FakeClock
from tomiris_hub.database.models import AgentRuntimeState
from tomiris_orchestrator.endpoint_security import EndpointValidator
from tomiris_orchestrator.health import AgentHealthProber

INGEST_SECRET = "health-ingest-secret-0123456789abcdef0123"  # noqa: S105
COMMAND_SECRET = "health-command-secret-0123456789abcdef012"  # noqa: S105


async def probe(clean_database: DatabaseHarness, capabilities: str) -> str:
    await add_endpoint(clean_database, "TEST_AGENT_001", "http://localhost")
    app = create_agent_runtime_app(
        AgentRuntimeSettings(
            _env_file=None,
            tomiris_agent_id="TEST_AGENT_001",
            tomiris_agent_role="test_agent",
            tomiris_agent_capabilities=capabilities,
            tomiris_agent_supported_assets="TEST",
            tomiris_hub_url="http://localhost",
            tomiris_hub_agent_secret=INGEST_SECRET,
            tomiris_orchestrator_command_secret=COMMAND_SECRET,
        ),
        clock=FakeClock(NOW),
        sink=NullSignalSink(),
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app))
    try:
        prober = AgentHealthProber(
            clean_database.session_factory,
            FakeClock(NOW),
            EndpointValidator(("hf.space",)),
            http_client=client,
        )
        return await prober.probe("TEST_AGENT_001")
    finally:
        await client.aclose()


async def test_capability_handshake_healthy_and_drift_is_degraded(
    clean_database: DatabaseHarness,
) -> None:
    assert await probe(clean_database, "signal_ingestion") == "HEALTHY"
    async with clean_database.session_factory() as session:
        state = await session.get(AgentRuntimeState, "TEST_AGENT_001")
        assert state is not None and state.last_error_code is None


async def test_runtime_cannot_self_authorize_capability(clean_database: DatabaseHarness) -> None:
    assert await probe(clean_database, "signal_ingestion,admin") == "DEGRADED"
    async with clean_database.session_factory() as session:
        state = await session.get(AgentRuntimeState, "TEST_AGENT_001")
        assert state is not None
        assert state.last_error_code == "AGENT_CAPABILITY_MISMATCH"
