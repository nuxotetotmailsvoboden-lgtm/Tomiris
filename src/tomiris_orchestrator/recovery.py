from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tomiris_hub.core.clock import Clock
from tomiris_hub.database.models import AgentTask, OrchestrationRun, Signal
from tomiris_orchestrator.audit import add_orchestration_event
from tomiris_orchestrator.metrics import OperationalMetrics
from tomiris_orchestrator.quorum import CompletenessEvaluator


class RecoveryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        evaluator: CompletenessEvaluator,
        *,
        batch_size: int = 500,
        metrics: OperationalMetrics | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.evaluator = evaluator
        self.batch_size = batch_size
        self.metrics = metrics or OperationalMetrics()

    async def reconcile(self) -> list[UUID]:
        now = self.clock.now()
        recovered: list[UUID] = []
        async with self.session_factory() as session, session.begin():
            runs = list(
                (
                    await session.scalars(
                        select(OrchestrationRun)
                        .where(
                            OrchestrationRun.status.in_(
                                ["CREATED", "DISPATCHING", "COLLECTING", "TIMED_OUT"]
                            )
                        )
                        .order_by(OrchestrationRun.created_at)
                        .limit(self.batch_size)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for run in runs:
                tasks = list(
                    (
                        await session.scalars(
                            select(AgentTask).where(
                                AgentTask.orchestration_run_id == run.orchestration_run_id
                            )
                        )
                    ).all()
                )
                signal_task_ids = set(
                    (
                        await session.scalars(
                            select(Signal.task_id).where(
                                Signal.orchestration_run_id == run.orchestration_run_id,
                                Signal.task_id.is_not(None),
                            )
                        )
                    ).all()
                )
                changed = False
                for task in tasks:
                    if task.task_id in signal_task_ids and task.status != "SIGNAL_RECEIVED":
                        task.status = "SIGNAL_RECEIVED"
                        task.signal_received_at = task.signal_received_at or now
                        task.lease_owner = None
                        task.lease_until = None
                        task.updated_at = now
                        changed = True
                    elif (
                        task.status == "DISPATCHING"
                        and task.lease_until is not None
                        and task.lease_until <= now
                    ):
                        task.status = "RETRY" if task.dispatch_deadline > now else "TIMED_OUT"
                        task.dispatch_after = now
                        task.lease_owner = None
                        task.lease_until = None
                        task.last_error_code = "WORKER_LEASE_EXPIRED"
                        task.updated_at = now
                        if task.status == "TIMED_OUT":
                            self.metrics.increment("agent_tasks_timed_out_total")
                        changed = True
                    elif (
                        task.status in {"ACKNOWLEDGED", "WAITING_SIGNAL"}
                        and task.signal_deadline <= now
                    ):
                        task.status = "TIMED_OUT"
                        task.last_error_code = "AGENT_SIGNAL_TIMEOUT"
                        task.updated_at = now
                        self.metrics.increment("agent_tasks_timed_out_total")
                        changed = True
                if changed or run.status == "TIMED_OUT":
                    if run.status == "TIMED_OUT":
                        run.status = "COLLECTING"
                    add_orchestration_event(
                        session,
                        now=now,
                        event_type="ORCHESTRATION_RECOVERED",
                        correlation_id=run.correlation_id,
                        causation_id=None,
                        run_id=run.orchestration_run_id,
                        snapshot_id=run.snapshot_id,
                        metadata={"reconciled_tasks": len(tasks)},
                    )
                    recovered.append(run.orchestration_run_id)
        for run_id in recovered:
            await self.evaluator.evaluate(run_id)
        return recovered
