from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tomiris_common.crypto import DerivedPerAgentSecretProvider
from tomiris_core_contracts.orchestration import OrchestrationPolicy
from tomiris_hub.core.clock import Clock
from tomiris_hub.core.config import Settings
from tomiris_orchestrator.backoff import ExponentialBackoff
from tomiris_orchestrator.client import AgentDispatchClient
from tomiris_orchestrator.dispatch import DispatchWorker
from tomiris_orchestrator.endpoint_security import EndpointValidator
from tomiris_orchestrator.metrics import OperationalMetrics
from tomiris_orchestrator.planner import OrchestrationPlan, OrchestrationPlanner
from tomiris_orchestrator.quorum import CompletenessEvaluator, CompletenessResult
from tomiris_orchestrator.recovery import RecoveryService
from tomiris_orchestrator.routing import CapabilityRouter


class OrchestratorService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        metrics: OperationalMetrics | None = None,
    ) -> None:
        if settings.tomiris_orchestrator_agent_master_secret is None:
            raise ValueError("TOMIRIS_ORCHESTRATOR_AGENT_MASTER_SECRET is required")
        self.metrics = metrics or OperationalMetrics()
        router = CapabilityRouter()
        self.planner = OrchestrationPlanner(session_factory, clock, router, self.metrics)
        self.evaluator = CompletenessEvaluator(session_factory, clock, self.metrics)
        provider = DerivedPerAgentSecretProvider(
            settings.tomiris_orchestrator_agent_master_secret.get_secret_value(),
            settings.orchestrator_command_key_id,
            "orchestrator-command",
        )
        client = AgentDispatchClient(
            orchestrator_id=settings.orchestrator_instance_id,
            command_key_id=settings.orchestrator_command_key_id,
            secret_provider=provider,
            endpoint_validator=EndpointValidator(settings.allowed_agent_host_suffixes),
            connect_timeout_seconds=settings.agent_connect_timeout_seconds,
            ack_timeout_seconds=settings.agent_ack_timeout_seconds,
            cold_start_grace_seconds=settings.agent_cold_start_grace_seconds,
        )
        self.dispatcher = DispatchWorker(
            session_factory=session_factory,
            clock=clock,
            transport=client,
            metrics=self.metrics,
            worker_id=settings.orchestrator_instance_id,
            batch_size=min(
                settings.orchestrator_dispatch_batch_size, settings.orchestrator_max_in_flight
            ),
            lease_seconds=(
                settings.agent_connect_timeout_seconds
                + settings.agent_ack_timeout_seconds
                + settings.agent_cold_start_grace_seconds
                + 5
            ),
            max_attempts=settings.agent_max_dispatch_attempts,
            backoff=ExponentialBackoff(
                settings.agent_retry_base_seconds, settings.agent_retry_max_seconds
            ),
            circuit_failure_threshold=settings.agent_circuit_failure_threshold,
            circuit_open_seconds=settings.agent_circuit_open_seconds,
        )
        self.recovery = RecoveryService(
            session_factory, clock, self.evaluator, metrics=self.metrics
        )

    async def create_test_run(
        self,
        *,
        snapshot_id: UUID,
        asset: str,
        policy: OrchestrationPolicy,
        context: dict[str, object] | None = None,
    ) -> OrchestrationPlan:
        return await self.planner.create(
            snapshot_id=snapshot_id,
            asset=asset,
            trigger_type="TEST",
            policy=policy,
            context=context,
        )

    async def cycle(self, run_id: UUID) -> CompletenessResult:
        await self.dispatcher.expire_dispatch_deadlines()
        await self.dispatcher.dispatch_once()
        await self.recovery.reconcile()
        return await self.evaluator.evaluate(run_id)
