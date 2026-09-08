from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

import pytest
from tests.conftest import DatabaseHarness
from tests.integration.test_phase02_orchestration import add_endpoint, policy
from tests.support import NOW, VALID_SNAPSHOT_ID

from tomiris_core_contracts.orchestration import AnalysisTaskAck, CapabilityRequirement
from tomiris_hub.core.clock import FakeClock
from tomiris_hub.database.models import AgentTask
from tomiris_orchestrator.backoff import ExponentialBackoff
from tomiris_orchestrator.client import (
    DispatchCommand,
    DispatchDisposition,
    DispatchResult,
)
from tomiris_orchestrator.dispatch import DispatchWorker
from tomiris_orchestrator.metrics import OperationalMetrics
from tomiris_orchestrator.planner import OrchestrationPlanner
from tomiris_orchestrator.routing import CapabilityRouter


@dataclass
class FakeTransport:
    result: DispatchResult
    calls: list[DispatchCommand] = field(default_factory=list)
    crash: bool = False

    async def dispatch(self, command: DispatchCommand, timestamp: int) -> DispatchResult:
        del timestamp
        self.calls.append(command)
        await asyncio.sleep(0)
        if self.crash:
            raise RuntimeError("simulated worker crash")
        return self.result


def worker(
    database: DatabaseHarness,
    clock: FakeClock,
    transport: FakeTransport,
    worker_id: str,
    *,
    threshold: int = 3,
) -> DispatchWorker:
    return DispatchWorker(
        session_factory=database.session_factory,
        clock=clock,
        transport=transport,
        metrics=OperationalMetrics(),
        worker_id=worker_id,
        batch_size=10,
        lease_seconds=5,
        max_attempts=3,
        backoff=ExponentialBackoff(1, 4, random_value=lambda: 0.0),
        circuit_failure_threshold=threshold,
        circuit_open_seconds=10,
    )


async def planned_task(database: DatabaseHarness, clock: FakeClock) -> AgentTask:
    await add_endpoint(database, "TEST_AGENT_001")
    plan = await OrchestrationPlanner(
        database.session_factory, clock, CapabilityRouter(), OperationalMetrics()
    ).create(
        snapshot_id=VALID_SNAPSHOT_ID,
        asset="TEST",
        trigger_type="TEST",
        policy=policy(
            CapabilityRequirement(capability="signal_ingestion", minimum_responses=1, max_agents=1)
        ),
    )
    async with database.session_factory() as session:
        task = await session.get(AgentTask, plan.task_ids[0])
        assert task is not None
        session.expunge(task)
        return task


def ack_result(task: AgentTask) -> DispatchResult:
    return DispatchResult(
        DispatchDisposition.ACKNOWLEDGED,
        ack=AnalysisTaskAck(
            task_id=task.task_id,
            agent_id=task.agent_id,
            accepted_at=NOW,
            runtime_version="0.2.0",
        ),
        latency_ms=1.0,
    )


async def test_concurrent_workers_dispatch_one_lease_owner(
    clean_database: DatabaseHarness,
) -> None:
    clock = FakeClock(NOW)
    task = await planned_task(clean_database, clock)
    transport = FakeTransport(ack_result(task))
    counts = await asyncio.gather(
        worker(clean_database, clock, transport, "worker-a").dispatch_once(),
        worker(clean_database, clock, transport, "worker-b").dispatch_once(),
    )
    assert sum(counts) == 1
    assert len(transport.calls) == 1
    async with clean_database.session_factory() as session:
        stored = await session.get(AgentTask, task.task_id)
        assert stored is not None and stored.status == "WAITING_SIGNAL"


async def test_expired_crash_lease_is_reclaimed(clean_database: DatabaseHarness) -> None:
    clock = FakeClock(NOW)
    task = await planned_task(clean_database, clock)
    crashed = FakeTransport(ack_result(task), crash=True)
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        await worker(clean_database, clock, crashed, "dead-worker").dispatch_once()
    async with clean_database.session_factory() as session:
        leased = await session.get(AgentTask, task.task_id)
        assert leased is not None and leased.status == "DISPATCHING"
    clock.advance_seconds(6)
    replacement = FakeTransport(ack_result(task))
    assert await worker(clean_database, clock, replacement, "replacement").dispatch_once() == 1
    assert len(replacement.calls) == 1


async def test_retry_is_bounded_and_circuit_opens(clean_database: DatabaseHarness) -> None:
    clock = FakeClock(NOW)
    task = await planned_task(clean_database, clock)
    retry = DispatchResult(DispatchDisposition.RETRYABLE, "AGENT_HTTP_429")
    transport = FakeTransport(retry)
    active_worker = worker(clean_database, clock, transport, "worker", threshold=2)
    assert await active_worker.dispatch_once() == 1
    clock.advance_seconds(1)
    assert await active_worker.dispatch_once() == 1
    async with clean_database.session_factory() as session:
        stored = await session.get(AgentTask, task.task_id)
        assert stored is not None
        assert stored.status == "RETRY"
        assert stored.last_error_code == "AGENT_HTTP_429"
        assert stored.dispatch_after >= NOW + timedelta(seconds=11)
