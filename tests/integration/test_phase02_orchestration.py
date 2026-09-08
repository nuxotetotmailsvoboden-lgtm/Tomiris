from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from tests.conftest import DatabaseHarness
from tests.support import NOW, VALID_SNAPSHOT_ID

from tomiris_core_contracts.orchestration import (
    CapabilityRequirement,
    OrchestrationPolicy,
)
from tomiris_hub.core.clock import FakeClock
from tomiris_hub.database.models import Agent, AgentEndpoint, AgentTask, OrchestrationRun
from tomiris_orchestrator.metrics import OperationalMetrics
from tomiris_orchestrator.planner import OrchestrationPlanner
from tomiris_orchestrator.quorum import CompletenessEvaluator
from tomiris_orchestrator.routing import CapabilityRouter


def policy(*requirements: CapabilityRequirement) -> OrchestrationPolicy:
    return OrchestrationPolicy(
        policy_version="phase-02-test",
        requirements=list(requirements),
        collection_timeout_seconds=60,
        dispatch_timeout_seconds=20,
        signal_timeout_seconds=30,
    )


async def add_endpoint(
    database: DatabaseHarness, agent_id: str, url: str = "http://127.0.0.1:9000"
) -> None:
    async with database.session_factory() as session, session.begin():
        session.add(
            AgentEndpoint(
                agent_id=agent_id,
                endpoint_url=url,
                transport="HTTP",
                enabled=True,
                environment="TEST",
                metadata_json={},
            )
        )


async def test_capability_routing_and_idempotent_plan(clean_database: DatabaseHarness) -> None:
    await add_endpoint(clean_database, "TEST_AGENT_001")
    planner = OrchestrationPlanner(
        clean_database.session_factory,
        FakeClock(NOW),
        CapabilityRouter(),
        OperationalMetrics(),
    )
    run_id = uuid4()
    selected_policy = policy(
        CapabilityRequirement(
            capability="signal_ingestion", required=True, minimum_responses=1, max_agents=1
        )
    )
    first = await planner.create(
        snapshot_id=VALID_SNAPSHOT_ID,
        asset="TEST",
        trigger_type="TEST",
        policy=selected_policy,
        orchestration_run_id=run_id,
    )
    second = await planner.create(
        snapshot_id=VALID_SNAPSHOT_ID,
        asset="TEST",
        trigger_type="TEST",
        policy=selected_policy,
        orchestration_run_id=run_id,
    )
    assert first.status == "DISPATCHING"
    assert len(first.task_ids) == 1
    assert second.task_ids == first.task_ids
    async with clean_database.session_factory() as session:
        assert len(list((await session.scalars(select(AgentTask))).all())) == 1


async def test_quorum_full_degraded_and_critical(clean_database: DatabaseHarness) -> None:
    await add_endpoint(clean_database, "TEST_AGENT_001")
    metrics = OperationalMetrics()
    planner = OrchestrationPlanner(
        clean_database.session_factory, FakeClock(NOW), CapabilityRouter(), metrics
    )
    evaluator = CompletenessEvaluator(clean_database.session_factory, FakeClock(NOW), metrics)

    full_plan = await planner.create(
        snapshot_id=VALID_SNAPSHOT_ID,
        asset="TEST",
        trigger_type="TEST",
        policy=policy(
            CapabilityRequirement(capability="signal_ingestion", minimum_responses=1, max_agents=1)
        ),
    )
    async with clean_database.session_factory() as session, session.begin():
        task = await session.get(AgentTask, full_plan.task_ids[0])
        assert task is not None
        task.status = "SIGNAL_RECEIVED"
        task.signal_received_at = NOW
    full = await evaluator.evaluate(full_plan.orchestration_run_id)
    assert full.status == "FULL"

    degraded_plan = await planner.create(
        snapshot_id=VALID_SNAPSHOT_ID,
        asset="TEST",
        trigger_type="TEST",
        policy=policy(
            CapabilityRequirement(capability="signal_ingestion", minimum_responses=1, max_agents=1),
            CapabilityRequirement(capability="optional.none", required=False),
        ),
    )
    async with clean_database.session_factory() as session, session.begin():
        task = await session.get(AgentTask, degraded_plan.task_ids[0])
        assert task is not None
        task.status = "SIGNAL_RECEIVED"
        task.signal_received_at = NOW
    degraded = await evaluator.evaluate(degraded_plan.orchestration_run_id)
    assert degraded.status == "DEGRADED"

    critical = await planner.create(
        snapshot_id=VALID_SNAPSHOT_ID,
        asset="TEST",
        trigger_type="TEST",
        policy=policy(CapabilityRequirement(capability="critical.none", critical=True)),
    )
    assert critical.status == "CRITICAL"
    async with clean_database.session_factory() as session:
        run = await session.get(OrchestrationRun, critical.orchestration_run_id)
        assert run is not None
        assert run.outcome == "INSUFFICIENT_DATA"


async def test_selector_scales_to_100_registry_entries(clean_database: DatabaseHarness) -> None:
    async with clean_database.session_factory() as session, session.begin():
        for index in range(100):
            agent_id = f"SCALE_AGENT_{index:03d}"
            session.add(
                Agent(
                    agent_id=agent_id,
                    name=agent_id,
                    role="test-scale",
                    enabled=True,
                    protocol_version="1.0",
                    capabilities=["test.scale"],
                    criticality="NORMAL",
                    supported_assets=["TEST"],
                    supported_evidence_types=[],
                    metadata_json={},
                )
            )
            session.add(
                AgentEndpoint(
                    agent_id=agent_id,
                    endpoint_url=f"http://127.0.0.1:{10_000 + index}",
                    transport="HTTP",
                    enabled=True,
                    environment="TEST",
                    metadata_json={},
                )
            )
    async with clean_database.session_factory() as session:
        selected = await CapabilityRouter().select(session, asset="TEST", capability="test.scale")
    assert len(selected) == 100
    assert selected[0].agent_id == "SCALE_AGENT_000"
    assert selected[-1].agent_id == "SCALE_AGENT_099"
    plan = await OrchestrationPlanner(
        clean_database.session_factory,
        FakeClock(NOW),
        CapabilityRouter(),
        OperationalMetrics(),
    ).create(
        snapshot_id=VALID_SNAPSHOT_ID,
        asset="TEST",
        trigger_type="TEST",
        policy=policy(
            CapabilityRequirement(capability="test.scale", minimum_responses=100, max_agents=100)
        ),
    )
    assert len(plan.task_ids) == 100
