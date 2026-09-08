from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tomiris_hub.core.clock import Clock
from tomiris_hub.database.models import (
    AgentEndpoint,
    AgentRuntimeState,
    AgentTask,
    OrchestrationRun,
)
from tomiris_orchestrator.audit import add_orchestration_event
from tomiris_orchestrator.backoff import ExponentialBackoff
from tomiris_orchestrator.client import (
    DispatchCommand,
    DispatchDisposition,
    DispatchResult,
)
from tomiris_orchestrator.metrics import OperationalMetrics

logger = logging.getLogger(__name__)


class DispatchTransport(Protocol):
    async def dispatch(self, command: DispatchCommand, timestamp: int) -> DispatchResult: ...


class DispatchWorker:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        transport: DispatchTransport,
        metrics: OperationalMetrics,
        worker_id: str,
        batch_size: int,
        lease_seconds: float,
        max_attempts: int,
        backoff: ExponentialBackoff,
        circuit_failure_threshold: int,
        circuit_open_seconds: int,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.transport = transport
        self.metrics = metrics
        self.worker_id = worker_id
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_open_seconds = circuit_open_seconds

    async def dispatch_once(self) -> int:
        commands = await self._claim()
        for command in commands:
            result = await self.transport.dispatch(command, int(self.clock.now().timestamp()))
            await self._record_result(command, result)
        return len(commands)

    async def _claim(self) -> Sequence[DispatchCommand]:
        now = self.clock.now()
        commands: list[DispatchCommand] = []
        async with self.session_factory() as session, session.begin():
            tasks = (
                await session.scalars(
                    select(AgentTask)
                    .where(
                        or_(
                            and_(
                                AgentTask.status.in_(["PENDING", "RETRY"]),
                                AgentTask.dispatch_after <= now,
                            ),
                            and_(
                                AgentTask.status == "DISPATCHING",
                                AgentTask.lease_until < now,
                            ),
                        ),
                        AgentTask.dispatch_deadline > now,
                    )
                    .order_by(AgentTask.priority.desc(), AgentTask.created_at)
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for task in tasks:
                run = await session.get(OrchestrationRun, task.orchestration_run_id)
                endpoint = await session.get(AgentEndpoint, task.agent_id)
                state = await session.get(AgentRuntimeState, task.agent_id, with_for_update=True)
                if state is None:
                    state = AgentRuntimeState(
                        agent_id=task.agent_id,
                        availability="UNKNOWN",
                        consecutive_failures=0,
                        circuit_state="CLOSED",
                        updated_at=now,
                    )
                    session.add(state)
                    await session.flush()
                if run is None or run.status in {
                    "FULL",
                    "DEGRADED",
                    "CRITICAL",
                    "FAILED",
                    "TIMED_OUT",
                    "CANCELLED",
                }:
                    task.status = "CANCELLED"
                    task.updated_at = now
                    continue
                if endpoint is None or not endpoint.enabled:
                    task.status = "FAILED"
                    task.last_error_code = "AGENT_ENDPOINT_MISSING"
                    task.updated_at = now
                    self.metrics.increment("agent_tasks_failed_total")
                    continue
                if state.circuit_state == "OPEN":
                    if state.circuit_open_until is not None and state.circuit_open_until > now:
                        task.status = "RETRY"
                        task.dispatch_after = state.circuit_open_until
                        task.last_error_code = "AGENT_CIRCUIT_OPEN"
                        task.updated_at = now
                        continue
                    state.circuit_state = "HALF_OPEN"
                    state.updated_at = now
                task.status = "DISPATCHING"
                task.attempt_count += 1
                task.lease_owner = self.worker_id
                task.lease_until = now + timedelta(seconds=self.lease_seconds)
                task.updated_at = now
                add_orchestration_event(
                    session,
                    now=now,
                    event_type="TASK_DISPATCH_STARTED",
                    correlation_id=run.correlation_id,
                    causation_id=task.causation_id,
                    run_id=run.orchestration_run_id,
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    snapshot_id=task.snapshot_id,
                    metadata={"attempt": task.attempt_count, "worker_id": self.worker_id},
                )
                commands.append(
                    DispatchCommand(
                        task_id=task.task_id,
                        orchestration_run_id=task.orchestration_run_id,
                        snapshot_id=task.snapshot_id,
                        agent_id=task.agent_id,
                        asset=task.asset,
                        required_capability=task.required_capability,
                        priority=task.priority,
                        created_at=task.created_at,
                        signal_deadline=task.signal_deadline,
                        correlation_id=run.correlation_id,
                        causation_id=task.causation_id,
                        context=task.context_json,
                        endpoint_url=endpoint.endpoint_url,
                        endpoint_environment=endpoint.environment,
                    )
                )
        return commands

    async def _record_result(self, command: DispatchCommand, result: DispatchResult) -> None:
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            task = await session.get(AgentTask, command.task_id, with_for_update=True)
            state = await session.get(AgentRuntimeState, command.agent_id, with_for_update=True)
            run = await session.get(OrchestrationRun, command.orchestration_run_id)
            if task is None or state is None or run is None:
                return
            if task.status == "SIGNAL_RECEIVED":
                return
            if task.status != "DISPATCHING" or task.lease_owner != self.worker_id:
                return
            logger.info(
                "agent_dispatch_result",
                extra={
                    "orchestration_run_id": str(command.orchestration_run_id),
                    "task_id": str(command.task_id),
                    "agent_id": command.agent_id,
                    "snapshot_id": str(command.snapshot_id),
                    "correlation_id": str(command.correlation_id),
                    "status": result.disposition.value,
                    "attempt": task.attempt_count,
                    "latency": result.latency_ms,
                    "reason_code": result.error_code,
                },
            )
            task.lease_owner = None
            task.lease_until = None
            task.updated_at = now
            state.updated_at = now
            if result.latency_ms is not None:
                state.latency_ms = result.latency_ms
                self.metrics.observe("agent_ack_latency", result.latency_ms)
                self.metrics.observe("agent_dispatch_latency", result.latency_ms)
            if result.disposition == DispatchDisposition.ACKNOWLEDGED:
                task.status = "WAITING_SIGNAL"
                task.acknowledged_at = result.ack.accepted_at if result.ack else now
                task.last_error_code = None
                state.availability = "HEALTHY"
                state.last_seen_at = now
                state.last_ack_at = now
                state.last_success_at = now
                state.consecutive_failures = 0
                state.circuit_state = "CLOSED"
                state.circuit_open_until = None
                run.status = "COLLECTING"
                self.metrics.increment("agent_tasks_acknowledged_total")
                add_orchestration_event(
                    session,
                    now=now,
                    event_type="TASK_ACKNOWLEDGED",
                    correlation_id=run.correlation_id,
                    causation_id=task.causation_id,
                    run_id=run.orchestration_run_id,
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    snapshot_id=task.snapshot_id,
                    metadata={
                        "attempt": task.attempt_count,
                        "latency_ms": result.latency_ms or 0.0,
                    },
                )
                return

            state.consecutive_failures += 1
            state.last_error_code = result.error_code
            state.availability = "DEGRADED"
            if state.consecutive_failures >= self.circuit_failure_threshold:
                state.circuit_state = "OPEN"
                state.circuit_open_until = now + timedelta(seconds=self.circuit_open_seconds)
                self.metrics.increment("agent_circuit_open_total")
                add_orchestration_event(
                    session,
                    now=now,
                    event_type="AGENT_CIRCUIT_OPENED",
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                    run_id=run.orchestration_run_id,
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    snapshot_id=task.snapshot_id,
                    outcome="REJECTED",
                    reason_code=result.error_code,
                )

            retryable = result.disposition == DispatchDisposition.RETRYABLE
            can_retry = (
                retryable
                and task.attempt_count < self.max_attempts
                and now < task.dispatch_deadline
            )
            if can_retry:
                task.status = "RETRY"
                delay = self.backoff.delay(task.attempt_count)
                retry_at = now + timedelta(seconds=delay)
                if state.circuit_state == "OPEN" and state.circuit_open_until is not None:
                    retry_at = max(retry_at, state.circuit_open_until)
                task.dispatch_after = retry_at
                task.last_error_code = result.error_code
                self.metrics.increment("agent_dispatch_retries_total")
                add_orchestration_event(
                    session,
                    now=now,
                    event_type="TASK_RETRY_SCHEDULED",
                    correlation_id=run.correlation_id,
                    causation_id=task.causation_id,
                    run_id=run.orchestration_run_id,
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    snapshot_id=task.snapshot_id,
                    outcome="REJECTED",
                    reason_code=result.error_code,
                    metadata={
                        "attempt": task.attempt_count,
                        "dispatch_after": retry_at.isoformat(),
                    },
                )
            else:
                task.status = "FAILED"
                task.last_error_code = result.error_code
                state.availability = "UNAVAILABLE"
                self.metrics.increment("agent_tasks_failed_total")
                add_orchestration_event(
                    session,
                    now=now,
                    event_type="TASK_FAILED",
                    correlation_id=run.correlation_id,
                    causation_id=task.causation_id,
                    run_id=run.orchestration_run_id,
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    snapshot_id=task.snapshot_id,
                    outcome="REJECTED",
                    reason_code=result.error_code,
                    metadata={"attempt": task.attempt_count},
                )

    async def expire_dispatch_deadlines(self) -> int:
        now = self.clock.now()
        expired = 0
        async with self.session_factory() as session, session.begin():
            tasks = (
                await session.scalars(
                    select(AgentTask)
                    .where(
                        AgentTask.status.in_(["PENDING", "RETRY", "DISPATCHING"]),
                        AgentTask.dispatch_deadline <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for task in tasks:
                task.status = "TIMED_OUT"
                task.last_error_code = "AGENT_ACK_TIMEOUT"
                task.lease_owner = None
                task.lease_until = None
                task.updated_at = now
                run = await session.get(OrchestrationRun, task.orchestration_run_id)
                if run is not None:
                    add_orchestration_event(
                        session,
                        now=now,
                        event_type="TASK_TIMED_OUT",
                        correlation_id=run.correlation_id,
                        causation_id=task.causation_id,
                        run_id=run.orchestration_run_id,
                        task_id=task.task_id,
                        agent_id=task.agent_id,
                        snapshot_id=task.snapshot_id,
                        outcome="REJECTED",
                        reason_code="AGENT_ACK_TIMEOUT",
                    )
                expired += 1
        self.metrics.increment("agent_tasks_timed_out_total", expired)
        return expired
