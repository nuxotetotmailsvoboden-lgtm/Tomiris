from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from tests.conftest import DatabaseHarness
from tests.e2e.test_phase02_e2e import serve
from tests.phase03_support import StaticMarketDataProvider, load_pilot_definitions, make_series
from tests.phase04_support import ETH_FUTURES, ETH_SPOT, book_delta, book_snapshot
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
from tomiris_hub.database.models import (
    Agent,
    AgentEndpoint,
    MarketSnapshot,
    OrchestrationRun,
    Signal,
)
from tomiris_market_data.adapters import observation_to_event, ohlcv_series_to_event
from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.orderbook import OrderBookSynchronizer
from tomiris_market_data.quality import MarketDataQualityEngine
from tomiris_market_data.service import MarketDataCollector
from tomiris_market_data.snapshot import (
    SnapshotRequirement,
    SnapshotRequirementItem,
    VerifiedMarketSnapshotBuilder,
)
from tomiris_market_data.store import InMemoryRecentMarketEventStore
from tomiris_market_data.time import DeterministicClock
from tomiris_orchestrator.errors import PlanningError
from tomiris_orchestrator.service import OrchestratorService

HUB_ROOT = "phase04-hub-root-0123456789abcdef0123456789"  # noqa: S105
COMMAND_ROOT = "phase04-command-root-0123456789abcdef01234"  # noqa: S105


async def test_verified_data_plane_to_pilot_hub_postgresql_orchestrator_is_full(
    clean_database: DatabaseHarness,
) -> None:
    clock = SystemClock()
    now = clock.now()
    definition = load_pilot_definitions()["ETH_TECHNICAL_001"]
    canonical = ETH_SPOT
    store = InMemoryRecentMarketEventStore(max_events=100, max_bytes=2_000_000)
    reports = {}
    requirement_items = []
    for data_requirement in definition.required_data:
        series = make_series(
            instrument="ETHUSDT",
            timeframe=data_requirement.timeframe,
            as_of=now,
            provider="fixture",
        )
        event = ohlcv_series_to_event(series, instrument=canonical, clock=DeterministicClock(now))
        await store.append(event)
        reports[event.event_id] = MarketDataQualityEngine().evaluate_event(event, observed_at=now)
        requirement_items.append(
            SnapshotRequirementItem(
                instrument=canonical,
                data_type=MarketDataType.OHLCV,
                qualifier=data_requirement.timeframe.value,
                required=True,
                max_age_seconds=data_requirement.max_data_age_seconds,
            )
        )
    verified = await VerifiedMarketSnapshotBuilder(store, clock=DeterministicClock(now)).build(
        snapshot_id=uuid4(),
        as_of=now,
        requirement=SnapshotRequirement(
            items=tuple(requirement_items), max_temporal_skew_seconds=0
        ),
        quality_reports=reports,
    )
    verified.require_analysis_safe()

    settings = build_test_settings(
        clean_database.url,
        agent_auth_mode="derived",
        tomiris_hub_ingest_secret=None,
        tomiris_hub_agent_master_secret=HUB_ROOT,
        tomiris_orchestrator_agent_master_secret=COMMAND_ROOT,
        orchestrator_enabled=True,
        orchestrator_instance_id="ORCHESTRATOR_PHASE04_E2E",
        agent_connect_timeout_seconds=1,
        agent_ack_timeout_seconds=3,
        agent_cold_start_grace_seconds=1,
        agent_retry_base_seconds=1,
        agent_retry_max_seconds=2,
    )
    ingest_secret = derive_agent_secret(HUB_ROOT, definition.agent_id, "hub-ingest", "current")
    command_secret = derive_agent_secret(
        COMMAND_ROOT, definition.agent_id, "orchestrator-command", "current"
    )
    async with AsyncExitStack() as stack:
        hub_url = await stack.enter_async_context(serve(create_app(settings, clock=clock)))
        role = create_builtin_role_registry().build(definition)
        runtime = create_agent_runtime_app(
            AgentRuntimeSettings(
                _env_file=None,
                tomiris_agent_id=definition.agent_id,
                tomiris_agent_role=definition.role_id,
                tomiris_agent_capabilities=",".join(definition.capabilities),
                tomiris_agent_supported_assets=",".join(definition.supported_assets),
                tomiris_hub_url=hub_url,
                tomiris_hub_agent_secret=ingest_secret,
                tomiris_orchestrator_id="ORCHESTRATOR_PHASE04_E2E",
                tomiris_orchestrator_command_secret=command_secret,
            ),
            handler=AnalyticalRoleHandler(
                role,
                MarketDataCollector(StaticMarketDataProvider()),
                RoleDataPlanner(),
                clock,
            ),
            clock=clock,
            sink=HubSignalSink(HubClient(hub_url, definition.agent_id, "current", ingest_secret)),
        )
        runtime_url = await stack.enter_async_context(serve(runtime))
        async with clean_database.session_factory() as session, session.begin():
            session.add(
                MarketSnapshot(
                    snapshot_id=verified.manifest.snapshot_id,
                    created_at=now,
                    expires_at=now + timedelta(minutes=5),
                    status="OPEN",
                    context_version="phase-04-verified.v1",
                    metadata_json={
                        "fingerprint": verified.manifest.content_fingerprint,
                        "quality": verified.manifest.quality_state.value,
                        "safe_for_analysis": verified.manifest.safe_for_analysis,
                    },
                )
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
                    supported_evidence_types=["technical_feature"],
                    metadata_json={"config_version": definition.config_version},
                )
            )
            await session.flush()
            session.add(
                AgentEndpoint(
                    agent_id=definition.agent_id,
                    endpoint_url=runtime_url,
                    transport="HTTP",
                    enabled=True,
                    environment="TEST",
                    metadata_json={},
                )
            )
        orchestrator = OrchestratorService(
            settings=settings,
            session_factory=clean_database.session_factory,
            clock=clock,
        )
        plan = await orchestrator.create_test_run(
            snapshot_id=verified.manifest.snapshot_id,
            asset="ETHUSDT",
            policy=OrchestrationPolicy(
                policy_version="phase-04-e2e.v1",
                requirements=[
                    CapabilityRequirement(
                        capability=definition.capabilities[0],
                        required=True,
                        critical=True,
                        minimum_responses=1,
                        max_agents=1,
                    )
                ],
                collection_timeout_seconds=30,
                dispatch_timeout_seconds=10,
                signal_timeout_seconds=20,
            ),
            context={"market_snapshot_fingerprint": verified.manifest.content_fingerprint},
        )
        assert await orchestrator.dispatcher.dispatch_once() == 1
        for _ in range(100):
            completion = await orchestrator.evaluator.evaluate(plan.orchestration_run_id)
            if completion.completed:
                break
            await asyncio.sleep(0.05)
        assert completion.status == "FULL"
        async with clean_database.session_factory() as session:
            signal = await session.scalar(
                select(Signal).where(Signal.agent_id == definition.agent_id)
            )
        assert signal is not None
        assert signal.snapshot_id == verified.manifest.snapshot_id


async def test_corrupted_book_makes_snapshot_ineligible_before_orchestration(
    clean_database: DatabaseHarness,
) -> None:
    clock = SystemClock()
    now = clock.now()
    synchronizer = OrderBookSynchronizer(ETH_FUTURES, "fixture-provider")
    snapshot_observation = book_snapshot().model_copy(
        update={"exchange_timestamp": now, "received_at": now}
    )
    await synchronizer.bootstrap(snapshot_observation)
    gap = book_delta(102, 102, previous_id=101).model_copy(
        update={"exchange_timestamp": now, "received_at": now}
    )
    await synchronizer.apply_delta(gap)
    assert (await synchronizer.read()).safe_for_analysis is False
    event = observation_to_event(snapshot_observation, clock=DeterministicClock(now))
    store = InMemoryRecentMarketEventStore(max_events=10, max_bytes=100_000)
    await store.append(event)
    report = MarketDataQualityEngine().evaluate_event(
        event, observed_at=now, sequence_integrity=False
    )
    verified = await VerifiedMarketSnapshotBuilder(store, clock=DeterministicClock(now)).build(
        snapshot_id=uuid4(),
        as_of=now,
        requirement=SnapshotRequirement(
            items=(
                SnapshotRequirementItem(
                    instrument=ETH_FUTURES,
                    data_type=MarketDataType.ORDER_BOOK_SNAPSHOT,
                    required=True,
                    max_age_seconds=10,
                    minimum_depth=2,
                ),
            )
        ),
        quality_reports={event.event_id: report},
    )
    assert verified.manifest.safe_for_analysis is False
    assert "SEQUENCE_GAP" in verified.manifest.reason_codes
    async with clean_database.session_factory() as session, session.begin():
        session.add(
            MarketSnapshot(
                snapshot_id=verified.manifest.snapshot_id,
                created_at=now,
                expires_at=now + timedelta(minutes=5),
                status="INVALID",
                context_version="phase-04-quality-veto.v1",
                metadata_json={"reason_codes": list(verified.manifest.reason_codes)},
            )
        )
    settings = build_test_settings(
        clean_database.url,
        tomiris_orchestrator_agent_master_secret=COMMAND_ROOT,
        orchestrator_enabled=True,
    )
    orchestrator = OrchestratorService(
        settings=settings,
        session_factory=clean_database.session_factory,
        clock=clock,
    )
    with pytest.raises(PlanningError) as caught:
        await orchestrator.create_test_run(
            snapshot_id=verified.manifest.snapshot_id,
            asset="TEST",
            policy=OrchestrationPolicy(
                policy_version="phase-04-failure-e2e.v1",
                requirements=[
                    CapabilityRequirement(
                        capability="signal_ingestion",
                        required=True,
                        critical=True,
                        minimum_responses=1,
                        max_agents=1,
                    )
                ],
                collection_timeout_seconds=30,
                dispatch_timeout_seconds=10,
                signal_timeout_seconds=20,
            ),
        )
    assert caught.value.code == "SNAPSHOT_NOT_ELIGIBLE"
    async with clean_database.session_factory() as session:
        run_count = await session.scalar(select(func.count()).select_from(OrchestrationRun))
    assert run_count == 0
