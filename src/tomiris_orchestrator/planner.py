from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tomiris_common.validation import validate_bounded_json
from tomiris_core_contracts.orchestration import CapabilityRequirement, OrchestrationPolicy
from tomiris_hub.core.clock import Clock
from tomiris_hub.database.models import AgentTask, MarketSnapshot, OrchestrationRun
from tomiris_orchestrator.audit import add_orchestration_event
from tomiris_orchestrator.errors import PlanningError
from tomiris_orchestrator.metrics import OperationalMetrics
from tomiris_orchestrator.routing import CapabilityRouter, RoutedAgent


@dataclass(frozen=True)
class OrchestrationPlan:
    orchestration_run_id: UUID
    task_ids: tuple[UUID, ...]
    missing_required: tuple[str, ...]
    missing_optional: tuple[str, ...]
    status: str


class OrchestrationPlanner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        router: CapabilityRouter,
        metrics: OperationalMetrics,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock
        self.router = router
        self.metrics = metrics

    async def create(
        self,
        *,
        snapshot_id: UUID,
        asset: str,
        trigger_type: str,
        policy: OrchestrationPolicy,
        context: dict[str, object] | None = None,
        orchestration_run_id: UUID | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
    ) -> OrchestrationPlan:
        if trigger_type not in {"MANUAL", "TEST"}:
            raise PlanningError("INVALID_TRIGGER", "Phase 02 supports MANUAL and TEST only")
        now = self.clock.now()
        bounded_context = validate_bounded_json(
            context or {}, max_depth=4, max_items=50, max_string_length=2_000
        )
        run_id = orchestration_run_id or uuid4()
        correlation = correlation_id or uuid4()
        async with self.session_factory() as session, session.begin():
            existing = await session.get(OrchestrationRun, run_id)
            if existing is not None:
                existing_task_ids = tuple(
                    (
                        await session.scalars(
                            select(AgentTask.task_id)
                            .where(AgentTask.orchestration_run_id == run_id)
                            .order_by(AgentTask.task_id)
                        )
                    ).all()
                )
                metadata = existing.metadata_json
                raw_missing_required = metadata.get("missing_required", [])
                raw_missing_optional = metadata.get("missing_optional", [])
                missing_required_values = (
                    raw_missing_required if isinstance(raw_missing_required, list) else []
                )
                missing_optional_values = (
                    raw_missing_optional if isinstance(raw_missing_optional, list) else []
                )
                return OrchestrationPlan(
                    run_id,
                    existing_task_ids,
                    tuple(str(item) for item in missing_required_values),
                    tuple(str(item) for item in missing_optional_values),
                    existing.status,
                )
            snapshot = await session.get(MarketSnapshot, snapshot_id)
            if snapshot is None:
                raise PlanningError("SNAPSHOT_NOT_FOUND", "snapshot does not exist")
            if snapshot.status != "OPEN" or snapshot.expires_at <= now:
                raise PlanningError("SNAPSHOT_NOT_ELIGIBLE", "snapshot is not open and current")

            assignments: list[tuple[CapabilityRequirement, RoutedAgent]] = []
            missing_required: list[str] = []
            missing_optional: list[str] = []
            for requirement in policy.requirements:
                agents = await self.router.select(
                    session,
                    asset=asset,
                    capability=requirement.capability,
                    limit=requirement.max_agents,
                )
                if len(agents) < requirement.minimum_responses:
                    target = missing_required if requirement.required else missing_optional
                    target.append(requirement.capability)
                assignments.extend((requirement, agent) for agent in agents)

            status = "CRITICAL" if missing_required else "DISPATCHING"
            outcome = "INSUFFICIENT_DATA" if missing_required else None
            run = OrchestrationRun(
                orchestration_run_id=run_id,
                snapshot_id=snapshot_id,
                asset=asset,
                trigger_type=trigger_type,
                status=status,
                outcome=outcome,
                created_at=now,
                started_at=now,
                collection_deadline=now + timedelta(seconds=policy.collection_timeout_seconds),
                completed_at=now if missing_required else None,
                correlation_id=correlation,
                policy_version=policy.policy_version,
                metadata_json={
                    "policy": policy.model_dump(mode="json"),
                    "context": bounded_context,
                    "missing_required": missing_required,
                    "missing_optional": missing_optional,
                },
            )
            session.add(run)
            await session.flush()
            add_orchestration_event(
                session,
                now=now,
                event_type="ORCHESTRATION_CREATED",
                correlation_id=correlation,
                causation_id=causation_id,
                run_id=run_id,
                snapshot_id=snapshot_id,
                metadata={"asset": asset, "trigger_type": trigger_type},
            )
            task_ids: list[UUID] = []
            for requirement, routed in assignments:
                task_id = uuid4()
                task_ids.append(task_id)
                task = AgentTask(
                    task_id=task_id,
                    orchestration_run_id=run_id,
                    snapshot_id=snapshot_id,
                    agent_id=routed.agent_id,
                    asset=asset,
                    required_capability=requirement.capability,
                    required=requirement.required,
                    priority=100 if requirement.critical else 50,
                    criticality="CRITICAL" if requirement.critical else routed.criticality,
                    status="CANCELLED" if missing_required else "PENDING",
                    attempt_count=0,
                    dispatch_after=now,
                    dispatch_deadline=now + timedelta(seconds=policy.dispatch_timeout_seconds),
                    signal_deadline=min(
                        now + timedelta(seconds=policy.signal_timeout_seconds),
                        run.collection_deadline,
                    ),
                    context_json=bounded_context,
                    causation_id=causation_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(task)
                add_orchestration_event(
                    session,
                    now=now,
                    event_type="TASK_CREATED",
                    correlation_id=correlation,
                    causation_id=causation_id,
                    run_id=run_id,
                    task_id=task_id,
                    agent_id=routed.agent_id,
                    snapshot_id=snapshot_id,
                    metadata={"capability": requirement.capability},
                )
            if missing_required:
                add_orchestration_event(
                    session,
                    now=now,
                    event_type="ORCHESTRATION_CRITICAL",
                    correlation_id=correlation,
                    causation_id=causation_id,
                    run_id=run_id,
                    snapshot_id=snapshot_id,
                    outcome="REJECTED",
                    reason_code="RUN_QUORUM_FAILED",
                    metadata={"missing_capabilities": missing_required},
                )
        self.metrics.increment("orchestration_runs_total")
        self.metrics.increment("agent_tasks_created_total", len(task_ids))
        if missing_required:
            self.metrics.increment("orchestration_critical_total")
        return OrchestrationPlan(
            run_id,
            tuple(task_ids),
            tuple(missing_required),
            tuple(missing_optional),
            status,
        )
