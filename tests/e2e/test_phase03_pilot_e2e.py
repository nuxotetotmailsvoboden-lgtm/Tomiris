from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from tests.conftest import DatabaseHarness
from tests.e2e.test_phase02_e2e import serve
from tests.phase03_support import StaticMarketDataProvider, load_pilot_definitions
from tests.support import test_settings as build_test_settings

from tomiris_agent_roles.builtin import create_builtin_role_registry
from tomiris_agent_roles.planner import RoleDataPlanner
from tomiris_agent_runtime.analytical import AnalyticalRoleHandler
from tomiris_agent_runtime.application import create_agent_runtime_app
from tomiris_agent_runtime.config import AgentRuntimeSettings
from tomiris_agent_runtime.sink import HubSignalSink
from tomiris_agent_sdk.client import HubClient
from tomiris_common.crypto import derive_agent_secret
from tomiris_core_contracts.orchestration import CapabilityRequirement, OrchestrationPolicy
from tomiris_hub.application import create_app
from tomiris_hub.core.clock import SystemClock
from tomiris_hub.database.models import Agent, AgentEndpoint, MarketSnapshot, Signal
from tomiris_market_data.service import MarketDataCollector
from tomiris_orchestrator.service import OrchestratorService

HUB_ROOT = "phase03-hub-root-0123456789abcdef0123456789"  # noqa: S105
COMMAND_ROOT = "phase03-command-root-0123456789abcdef01234"  # noqa: S105


async def test_three_pilot_roles_real_http_hub_postgresql_cycle_is_full(
    clean_database: DatabaseHarness,
) -> None:
    clock = SystemClock()
    definitions = load_pilot_definitions()
    hub_settings = build_test_settings(
        clean_database.url,
        agent_auth_mode="derived",
        tomiris_hub_ingest_secret=None,
        tomiris_hub_agent_master_secret=HUB_ROOT,
        tomiris_orchestrator_agent_master_secret=COMMAND_ROOT,
        orchestrator_enabled=True,
        orchestrator_instance_id="ORCHESTRATOR_PHASE03_E2E",
        agent_connect_timeout_seconds=1,
        agent_ack_timeout_seconds=3,
        agent_cold_start_grace_seconds=1,
        agent_retry_base_seconds=1,
        agent_retry_max_seconds=2,
    )
    async with AsyncExitStack() as stack:
        hub_url = await stack.enter_async_context(serve(create_app(hub_settings, clock=clock)))
        runtime_origins: list[tuple[str, str]] = []
        for definition in definitions.values():
            ingest_secret = derive_agent_secret(
                HUB_ROOT, definition.agent_id, "hub-ingest", "current"
            )
            command_secret = derive_agent_secret(
                COMMAND_ROOT,
                definition.agent_id,
                "orchestrator-command",
                "current",
            )
            role = create_builtin_role_registry().build(definition)
            role_handler = AnalyticalRoleHandler(
                role,
                MarketDataCollector(StaticMarketDataProvider()),
                RoleDataPlanner(),
                clock,
            )
            runtime_settings = AgentRuntimeSettings(
                _env_file=None,
                tomiris_agent_id=definition.agent_id,
                tomiris_agent_role=definition.role_id,
                tomiris_agent_capabilities=",".join(definition.capabilities),
                tomiris_agent_supported_assets=",".join(definition.supported_assets),
                tomiris_hub_url=hub_url,
                tomiris_hub_agent_secret=ingest_secret,
                tomiris_orchestrator_id="ORCHESTRATOR_PHASE03_E2E",
                tomiris_orchestrator_command_secret=command_secret,
            )
            runtime = create_agent_runtime_app(
                runtime_settings,
                handler=role_handler,
                clock=clock,
                sink=HubSignalSink(
                    HubClient(
                        hub_url,
                        definition.agent_id,
                        "current",
                        ingest_secret,
                    )
                ),
            )
            origin = await stack.enter_async_context(serve(runtime))
            runtime_origins.append((definition.agent_id, origin))

        now = clock.now()
        snapshot_id = uuid4()
        async with clean_database.session_factory() as session, session.begin():
            session.add(
                MarketSnapshot(
                    snapshot_id=snapshot_id,
                    created_at=now - timedelta(seconds=1),
                    expires_at=now + timedelta(minutes=5),
                    status="OPEN",
                    context_version="phase-03-pilot-e2e",
                    metadata_json={"data_source": "deterministic-fixture"},
                )
            )
            for definition in definitions.values():
                evidence_type = (
                    "market_context"
                    if definition.agent_id == "BTC_CONTEXT_001"
                    else "technical_feature"
                )
                session.add(
                    Agent(
                        agent_id=definition.agent_id,
                        name=definition.agent_id,
                        role=definition.role_id,
                        enabled=True,
                        protocol_version="1.0",
                        capabilities=["signal_ingestion", *definition.capabilities],
                        criticality="NORMAL",
                        supported_assets=list(definition.supported_assets),
                        supported_evidence_types=[evidence_type],
                        metadata_json={"config_version": definition.config_version},
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
        plans = []
        for definition in definitions.values():
            capability = definition.capabilities[0]
            plans.append(
                await service.create_test_run(
                    snapshot_id=snapshot_id,
                    asset=definition.supported_assets[0],
                    policy=OrchestrationPolicy(
                        policy_version="phase-03-pilot-e2e.v1",
                        requirements=[
                            CapabilityRequirement(
                                capability=capability,
                                required=True,
                                critical=True,
                                minimum_responses=1,
                                max_agents=1,
                            )
                        ],
                        collection_timeout_seconds=45,
                        dispatch_timeout_seconds=10,
                        signal_timeout_seconds=30,
                    ),
                    context={"pilot_cycle": "fixture-three-agent"},
                )
            )
        assert await service.dispatcher.dispatch_once() == 3
        results = []
        for plan in plans:
            for _ in range(120):
                result = await service.evaluator.evaluate(plan.orchestration_run_id)
                if result.completed:
                    break
                await asyncio.sleep(0.05)
            results.append(result)
        assert [result.status for result in results] == ["FULL", "FULL", "FULL"]
        async with clean_database.session_factory() as session:
            signals = list((await session.scalars(select(Signal).order_by(Signal.agent_id))).all())
        assert len(signals) == 3
        assert {signal.agent_id for signal in signals} == set(definitions)
        assert {signal.role_id for signal in signals} == {
            "btc.market_context.v1",
            "eth.technical.v1",
            "sol.technical.v1",
        }
        assert all(signal.feature_pipeline_version == "technical-pipeline.v1" for signal in signals)
        assert all(
            signal.payload_json["metadata"]["agent_signal_is_trade_decision"] is False
            for signal in signals
        )
