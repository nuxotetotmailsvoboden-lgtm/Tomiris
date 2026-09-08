from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tomiris_core_contracts.orchestration import OrchestrationPolicy
from tomiris_hub.core.clock import Clock
from tomiris_hub.database.models import AgentTask, OrchestrationRun
from tomiris_orchestrator.audit import add_orchestration_event
from tomiris_orchestrator.metrics import OperationalMetrics

TERMINAL_TASK_STATES = {"SIGNAL_RECEIVED", "TIMED_OUT", "FAILED", "CANCELLED", "SKIPPED"}


@dataclass(frozen=True)
class CompletenessResult:
    status: str
    outcome: str | None
    completed: bool
    received: int
    expected: int
    missing_capabilities: tuple[str, ...]


class CompletenessEvaluator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        metrics: OperationalMetrics,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.metrics = metrics

    async def evaluate(self, run_id: UUID) -> CompletenessResult:
        now = self.clock.now()
        async with self.session_factory() as session, session.begin():
            run = await session.get(OrchestrationRun, run_id, with_for_update=True)
            if run is None:
                raise LookupError(f"orchestration run {run_id} not found")
            tasks = list(
                (
                    await session.scalars(
                        select(AgentTask)
                        .where(AgentTask.orchestration_run_id == run_id)
                        .order_by(AgentTask.task_id)
                    )
                ).all()
            )
            if run.status in {"FULL", "DEGRADED", "CRITICAL", "FAILED", "CANCELLED"}:
                return self._result_from_run(run, tasks)

            policy = OrchestrationPolicy.model_validate(run.metadata_json["policy"])
            missing: list[str] = []
            impossible = False
            critical_failure = False
            for requirement in policy.requirements:
                capability_tasks = [
                    task for task in tasks if task.required_capability == requirement.capability
                ]
                received = sum(task.status == "SIGNAL_RECEIVED" for task in capability_tasks)
                unfinished = sum(
                    task.status not in TERMINAL_TASK_STATES for task in capability_tasks
                )
                if requirement.required and received < requirement.minimum_responses:
                    missing.append(requirement.capability)
                    if received + unfinished < requirement.minimum_responses:
                        impossible = True
                if requirement.critical and any(
                    task.status in {"TIMED_OUT", "FAILED", "CANCELLED", "SKIPPED"}
                    for task in capability_tasks
                ):
                    critical_failure = True

            deadline_reached = now >= run.collection_deadline
            all_terminal = all(task.status in TERMINAL_TASK_STATES for task in tasks)
            all_received = all(task.status == "SIGNAL_RECEIVED" for task in tasks)
            missing_optional_plan = bool(run.metadata_json.get("missing_optional"))
            received_total = sum(task.status == "SIGNAL_RECEIVED" for task in tasks)

            if missing and (impossible or deadline_reached or all_terminal):
                status, outcome, reason = "CRITICAL", "INSUFFICIENT_DATA", "RUN_QUORUM_FAILED"
            elif critical_failure:
                status, outcome, reason = "CRITICAL", "INSUFFICIENT_DATA", "RUN_QUORUM_FAILED"
            elif all_received and not missing_optional_plan:
                status, outcome, reason = "FULL", "FULL", None
            elif all_terminal or deadline_reached:
                status, outcome, reason = "DEGRADED", "DEGRADED", "RUN_DEADLINE_EXCEEDED"
            else:
                return CompletenessResult(
                    status=run.status,
                    outcome=run.outcome,
                    completed=False,
                    received=received_total,
                    expected=len(tasks),
                    missing_capabilities=tuple(missing),
                )

            run.status = status
            run.outcome = outcome
            run.completed_at = now
            for task in tasks:
                if task.acknowledged_at is not None and task.signal_received_at is not None:
                    signal_latency_ms = max(
                        0.0,
                        (task.signal_received_at - task.acknowledged_at).total_seconds() * 1000,
                    )
                    self.metrics.observe("agent_signal_latency", signal_latency_ms)
            self.metrics.increment("agent_tasks_completed_total", received_total)
            event_type = f"ORCHESTRATION_{status}"
            add_orchestration_event(
                session,
                now=now,
                event_type=event_type,
                correlation_id=run.correlation_id,
                causation_id=None,
                run_id=run.orchestration_run_id,
                snapshot_id=run.snapshot_id,
                outcome="ACCEPTED" if status != "CRITICAL" else "REJECTED",
                reason_code=reason,
                metadata={
                    "received": received_total,
                    "expected": len(tasks),
                    "missing_capabilities": missing,
                },
            )
            self.metrics.increment(f"orchestration_{status.lower()}_total")
            return CompletenessResult(
                status=status,
                outcome=outcome,
                completed=True,
                received=received_total,
                expected=len(tasks),
                missing_capabilities=tuple(missing),
            )

    @staticmethod
    def _result_from_run(run: OrchestrationRun, tasks: list[AgentTask]) -> CompletenessResult:
        received = sum(task.status == "SIGNAL_RECEIVED" for task in tasks)
        raw_missing = run.metadata_json.get("missing_required", [])
        missing_values = raw_missing if isinstance(raw_missing, list) else []
        return CompletenessResult(
            status=run.status,
            outcome=run.outcome,
            completed=run.completed_at is not None,
            received=received,
            expected=len(tasks),
            missing_capabilities=tuple(str(item) for item in missing_values),
        )
