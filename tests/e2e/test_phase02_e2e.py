from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import uvicorn
from fastapi import FastAPI
from sqlalchemy import select
from tests.conftest import DatabaseHarness
from tests.support import test_settings as build_test_settings

from tomiris_agent_runtime.application import create_agent_runtime_app
from tomiris_agent_runtime.config import AgentRuntimeSettings
from tomiris_agent_runtime.sink import HubSignalSink
from tomiris_agent_sdk.client import HubClient
from tomiris_common.crypto import derive_agent_secret
from tomiris_core_contracts.orchestration import CapabilityRequirement, OrchestrationPolicy
from tomiris_hub.application import create_app
from tomiris_hub.core.clock import SystemClock
from tomiris_hub.database.models import Agent, AgentEndpoint, AgentTask, MarketSnapshot, Signal
from tomiris_orchestrator.service import OrchestratorService

HUB_ROOT = "phase02-hub-root-0123456789abcdef0123456789"  # noqa: S105
COMMAND_ROOT = "phase02-command-root-0123456789abcdef01234"  # noqa: S105


@asynccontextmanager
async def serve(app: FastAPI) -> AsyncIterator[str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    port = int(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.01)
    if not server.started:
        server.should_exit = True
        await task
        raise RuntimeError("test HTTP server failed to start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def test_real_http_postgresql_three_agent_flow_is_full(
    clean_database: DatabaseHarness,
) -> None:
    clock = SystemClock()
    hub_settings = build_test_settings(
        clean_database.url,
        agent_auth_mode="derived",
        tomiris_hub_ingest_secret=None,
        tomiris_hub_agent_master_secret=HUB_ROOT,
        tomiris_orchestrator_agent_master_secret=COMMAND_ROOT,
        orchestrator_enabled=True,
        orchestrator_instance_id="ORCHESTRATOR_E2E",
        agent_connect_timeout_seconds=1,
        agent_ack_timeout_seconds=2,
        agent_cold_start_grace_seconds=1,
        agent_retry_base_seconds=1,
        agent_retry_max_seconds=2,
    )
    hub_app = create_app(hub_settings, clock=clock)
    async with AsyncExitStack() as stack:
        hub_url = await stack.enter_async_context(serve(hub_app))
        runtime_origins: list[tuple[str, str]] = []
        for suffix in ("A", "B", "C"):
            agent_id = f"TEST_AGENT_{suffix}"
            ingest_secret = derive_agent_secret(HUB_ROOT, agent_id, "hub-ingest", "current")
            command_secret = derive_agent_secret(
                COMMAND_ROOT, agent_id, "orchestrator-command", "current"
            )
            runtime_settings = AgentRuntimeSettings(
                _env_file=None,
                tomiris_agent_id=agent_id,
                tomiris_agent_role="test-runtime",
                tomiris_agent_capabilities="test.echo",
                tomiris_agent_supported_assets="TEST",
                tomiris_hub_url=hub_url,
                tomiris_hub_agent_secret=ingest_secret,
                tomiris_orchestrator_id="ORCHESTRATOR_E2E",
                tomiris_orchestrator_command_secret=command_secret,
            )
            runtime_app = create_agent_runtime_app(
                runtime_settings,
                clock=clock,
                sink=HubSignalSink(HubClient(hub_url, agent_id, "current", ingest_secret)),
            )
            origin = await stack.enter_async_context(serve(runtime_app))
            runtime_origins.append((agent_id, origin))

        now = clock.now()
        snapshot_id = uuid4()
        async with clean_database.session_factory() as session, session.begin():
            session.add(
                MarketSnapshot(
                    snapshot_id=snapshot_id,
                    created_at=now - timedelta(seconds=1),
                    expires_at=now + timedelta(minutes=5),
                    status="OPEN",
                    context_version="phase-02-e2e",
                    metadata_json={"test_only": True},
                )
            )
            for agent_id, _origin in runtime_origins:
                session.add(
                    Agent(
                        agent_id=agent_id,
                        name=agent_id,
                        role="test-runtime",
                        enabled=True,
                        protocol_version="1.0",
                        capabilities=["signal_ingestion", "test.echo"],
                        criticality="NORMAL",
                        supported_assets=["TEST"],
                        supported_evidence_types=[],
                        metadata_json={"test_only": True},
                    )
                )
            await session.flush()
            for agent_id, origin in runtime_origins:
                session.add(
                    AgentEndpoint(
                        agent_id=agent_id,
                        endpoint_url=origin,
                        transport="HTTP",
                        enabled=True,
                        environment="TEST",
                        metadata_json={},
                    )
                )

        service = OrchestratorService(
            settings=hub_settings,
            session_factory=clean_database.session_factory,
            clock=clock,
        )
        plan = await service.create_test_run(
            snapshot_id=snapshot_id,
            asset="TEST",
            policy=OrchestrationPolicy(
                policy_version="phase-02-e2e",
                requirements=[
                    CapabilityRequirement(
                        capability="test.echo",
                        required=True,
                        minimum_responses=3,
                        max_agents=3,
                    )
                ],
                collection_timeout_seconds=30,
                dispatch_timeout_seconds=10,
                signal_timeout_seconds=20,
            ),
            context={"test": "real-http"},
        )
        assert await service.dispatcher.dispatch_once() == 3
        for _ in range(100):
            result = await service.evaluator.evaluate(plan.orchestration_run_id)
            if result.completed:
                break
            await asyncio.sleep(0.05)
        assert result.status == "FULL"
        assert result.received == 3
        async with clean_database.session_factory() as session:
            statuses = list(
                (
                    await session.scalars(
                        select(AgentTask.status).where(
                            AgentTask.orchestration_run_id == plan.orchestration_run_id
                        )
                    )
                ).all()
            )
            biases = list(
                (
                    await session.scalars(
                        select(Signal.bias).where(
                            Signal.orchestration_run_id == plan.orchestration_run_id
                        )
                    )
                ).all()
            )
        assert statuses == ["SIGNAL_RECEIVED"] * 3
        assert biases == ["ABSTAIN"] * 3


async def test_real_http_degraded_and_early_critical_outcomes(
    clean_database: DatabaseHarness,
) -> None:
    clock = SystemClock()
    hub_settings = build_test_settings(
        clean_database.url,
        agent_auth_mode="derived",
        tomiris_hub_ingest_secret=None,
        tomiris_hub_agent_master_secret=HUB_ROOT,
        tomiris_orchestrator_agent_master_secret=COMMAND_ROOT,
        orchestrator_enabled=True,
        orchestrator_instance_id="ORCHESTRATOR_E2E",
        agent_connect_timeout_seconds=1,
        agent_ack_timeout_seconds=2,
        agent_cold_start_grace_seconds=1,
        agent_retry_base_seconds=1,
        agent_retry_max_seconds=2,
    )
    agent_id = "TEST_AGENT_D"
    ingest_secret = derive_agent_secret(HUB_ROOT, agent_id, "hub-ingest", "current")
    command_secret = derive_agent_secret(COMMAND_ROOT, agent_id, "orchestrator-command", "current")
    async with AsyncExitStack() as stack:
        hub_url = await stack.enter_async_context(serve(create_app(hub_settings, clock=clock)))
        runtime = create_agent_runtime_app(
            AgentRuntimeSettings(
                _env_file=None,
                tomiris_agent_id=agent_id,
                tomiris_agent_role="test-runtime",
                tomiris_agent_capabilities="test.echo",
                tomiris_agent_supported_assets="TEST",
                tomiris_hub_url=hub_url,
                tomiris_hub_agent_secret=ingest_secret,
                tomiris_orchestrator_id="ORCHESTRATOR_E2E",
                tomiris_orchestrator_command_secret=command_secret,
            ),
            clock=clock,
            sink=HubSignalSink(HubClient(hub_url, agent_id, "current", ingest_secret)),
        )
        runtime_url = await stack.enter_async_context(serve(runtime))
        now = clock.now()
        snapshot_id = uuid4()
        async with clean_database.session_factory() as session, session.begin():
            session.add(
                MarketSnapshot(
                    snapshot_id=snapshot_id,
                    created_at=now - timedelta(seconds=1),
                    expires_at=now + timedelta(minutes=5),
                    status="OPEN",
                    context_version="phase-02-e2e",
                    metadata_json={"test_only": True},
                )
            )
            session.add(
                Agent(
                    agent_id=agent_id,
                    name=agent_id,
                    role="test-runtime",
                    enabled=True,
                    protocol_version="1.0",
                    capabilities=["signal_ingestion", "test.echo"],
                    criticality="NORMAL",
                    supported_assets=["TEST"],
                    supported_evidence_types=[],
                    metadata_json={"test_only": True},
                )
            )
            await session.flush()
            session.add(
                AgentEndpoint(
                    agent_id=agent_id,
                    endpoint_url=runtime_url,
                    transport="HTTP",
                    enabled=True,
                    environment="TEST",
                    metadata_json={},
                )
            )
        service = OrchestratorService(
            settings=hub_settings,
            session_factory=clean_database.session_factory,
            clock=clock,
        )
        degraded_plan = await service.create_test_run(
            snapshot_id=snapshot_id,
            asset="TEST",
            policy=OrchestrationPolicy(
                policy_version="phase-02-degraded-e2e",
                requirements=[
                    CapabilityRequirement(capability="test.echo", max_agents=1),
                    CapabilityRequirement(capability="test.optional", required=False),
                ],
                collection_timeout_seconds=20,
                dispatch_timeout_seconds=5,
                signal_timeout_seconds=10,
            ),
        )
        await service.dispatcher.dispatch_once()
        for _ in range(100):
            degraded = await service.evaluator.evaluate(degraded_plan.orchestration_run_id)
            if degraded.completed:
                break
            await asyncio.sleep(0.05)
        assert degraded.status == "DEGRADED"

        critical_plan = await service.create_test_run(
            snapshot_id=snapshot_id,
            asset="TEST",
            policy=OrchestrationPolicy(
                policy_version="phase-02-critical-e2e",
                requirements=[CapabilityRequirement(capability="test.critical", critical=True)],
                collection_timeout_seconds=20,
                dispatch_timeout_seconds=5,
                signal_timeout_seconds=10,
            ),
        )
        assert critical_plan.status == "CRITICAL"
        critical = await service.evaluator.evaluate(critical_plan.orchestration_run_id)
        assert critical.outcome == "INSUFFICIENT_DATA"
