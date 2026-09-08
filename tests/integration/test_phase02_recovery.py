from __future__ import annotations

from tests.conftest import DatabaseHarness
from tests.integration.test_phase02_orchestration import add_endpoint, policy
from tests.support import NOW, VALID_SNAPSHOT_ID

from tomiris_core_contracts.orchestration import CapabilityRequirement
from tomiris_hub.core.clock import FakeClock
from tomiris_hub.database.models import AgentTask, OrchestrationRun
from tomiris_orchestrator.metrics import OperationalMetrics
from tomiris_orchestrator.planner import OrchestrationPlanner
from tomiris_orchestrator.quorum import CompletenessEvaluator
from tomiris_orchestrator.recovery import RecoveryService
from tomiris_orchestrator.routing import CapabilityRouter


async def test_restart_recovers_expired_lease_and_waiting_signal(
    clean_database: DatabaseHarness,
) -> None:
    await add_endpoint(clean_database, "TEST_AGENT_001")
    clock = FakeClock(NOW)
    metrics = OperationalMetrics()
    planner = OrchestrationPlanner(
        clean_database.session_factory, clock, CapabilityRouter(), metrics
    )
    selected_policy = policy(
        CapabilityRequirement(capability="signal_ingestion", minimum_responses=1, max_agents=1)
    )
    leased = await planner.create(
        snapshot_id=VALID_SNAPSHOT_ID,
        asset="TEST",
        trigger_type="TEST",
        policy=selected_policy,
    )
    async with clean_database.session_factory() as session, session.begin():
        task = await session.get(AgentTask, leased.task_ids[0])
        assert task is not None
        task.status = "DISPATCHING"
        task.lease_owner = "dead-worker"
        task.lease_until = NOW
    clock.advance_seconds(1)
    evaluator = CompletenessEvaluator(clean_database.session_factory, clock, metrics)
    recovery = RecoveryService(clean_database.session_factory, clock, evaluator)
    recovered = await recovery.reconcile()
    assert leased.orchestration_run_id in recovered
    async with clean_database.session_factory() as session:
        task = await session.get(AgentTask, leased.task_ids[0])
        assert task is not None and task.status == "RETRY"
        assert task.lease_owner is None

    async with clean_database.session_factory() as session, session.begin():
        task = await session.get(AgentTask, leased.task_ids[0])
        assert task is not None
        task.status = "WAITING_SIGNAL"
    clock.advance_seconds(30)
    recovered_again = await recovery.reconcile()
    assert leased.orchestration_run_id in recovered_again
    async with clean_database.session_factory() as session:
        task = await session.get(AgentTask, leased.task_ids[0])
        run = await session.get(OrchestrationRun, leased.orchestration_run_id)
        assert task is not None and task.status == "TIMED_OUT"
        assert run is not None and run.status == "CRITICAL"
        assert run.outcome == "INSUFFICIENT_DATA"
