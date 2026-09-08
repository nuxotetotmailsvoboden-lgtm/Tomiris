from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from uuid import uuid4

from tomiris_core_contracts.orchestration import CapabilityRequirement, OrchestrationPolicy
from tomiris_hub.core.clock import SystemClock
from tomiris_hub.core.config import get_settings
from tomiris_hub.database.models import MarketSnapshot
from tomiris_hub.database.session import build_engine, build_session_factory
from tomiris_orchestrator.service import OrchestratorService


async def run(asset: str, capability: str, agents: int) -> int:
    settings = get_settings()
    clock = SystemClock()
    engine = build_engine(settings.database_url, settings.database_connect_timeout_seconds)
    factory = build_session_factory(engine)
    snapshot_id = uuid4()
    now = clock.now()
    try:
        async with factory() as session, session.begin():
            session.add(
                MarketSnapshot(
                    snapshot_id=snapshot_id,
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                    status="OPEN",
                    context_version="phase-02-manual-test",
                    metadata_json={"created_by": "run_test_orchestration.py"},
                )
            )
        service = OrchestratorService(settings=settings, session_factory=factory, clock=clock)
        plan = await service.create_test_run(
            snapshot_id=snapshot_id,
            asset=asset,
            policy=OrchestrationPolicy(
                policy_version="phase-02-manual-test",
                requirements=[
                    CapabilityRequirement(
                        capability=capability,
                        required=True,
                        minimum_responses=agents,
                        max_agents=agents,
                    )
                ],
                collection_timeout_seconds=settings.agent_signal_timeout_seconds,
                dispatch_timeout_seconds=max(1, int(settings.agent_ack_timeout_seconds)),
                signal_timeout_seconds=settings.agent_signal_timeout_seconds,
            ),
            context={"test_only": True},
        )
        result = await service.evaluator.evaluate(plan.orchestration_run_id)
        while not result.completed:
            result = await service.cycle(plan.orchestration_run_id)
            if not result.completed:
                await asyncio.sleep(settings.orchestrator_poll_interval_seconds)
        print(
            json.dumps(
                {
                    "orchestration_run_id": str(plan.orchestration_run_id),
                    "snapshot_id": str(snapshot_id),
                    "status": result.status,
                    "outcome": result.outcome,
                    "agents_received": result.received,
                    "agents_expected": result.expected,
                    "missing_capabilities": result.missing_capabilities,
                    "test_only": True,
                },
                separators=(",", ":"),
            )
        )
        return 0 if result.status in {"FULL", "DEGRADED"} else 2
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one durable Phase 02 system test")
    parser.add_argument("--asset", default="TEST")
    parser.add_argument("--capability", default="test.echo")
    parser.add_argument("--agents", type=int, default=3)
    arguments = parser.parse_args()
    if arguments.agents < 1 or arguments.agents > 500:
        parser.error("--agents must be between 1 and 500")
    raise SystemExit(
        asyncio.run(run(arguments.asset.upper(), arguments.capability, arguments.agents))
    )


if __name__ == "__main__":
    main()
