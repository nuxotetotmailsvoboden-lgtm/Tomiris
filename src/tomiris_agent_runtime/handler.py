from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import uuid4

from tomiris_core_contracts.orchestration import AnalysisTaskRequest
from tomiris_core_contracts.signals import Bias, SignalEnvelope
from tomiris_hub.core.clock import Clock


class AnalysisHandler(Protocol):
    async def analyze(self, task: AnalysisTaskRequest) -> SignalEnvelope: ...


class TestAnalysisHandler:
    """Deterministic Phase 02 handler; it performs no market analysis."""

    def __init__(self, clock: Clock, *, delay_seconds: float = 0.0) -> None:
        self.clock = clock
        self.delay_seconds = delay_seconds

    async def analyze(self, task: AnalysisTaskRequest) -> SignalEnvelope:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        now = self.clock.now()
        return SignalEnvelope(
            protocol_version="1.0",
            message_id=uuid4(),
            agent_id=task.agent_id,
            agent_run_id=uuid4(),
            snapshot_id=task.snapshot_id,
            task_id=task.task_id,
            orchestration_run_id=task.orchestration_run_id,
            correlation_id=task.correlation_id,
            causation_id=task.task_id,
            asset=task.asset,
            bias=Bias.ABSTAIN,
            confidence=0,
            impact=0,
            time_horizon="phase-02-system-test",
            evidence=[],
            risk_flags=["TEST_ONLY_NO_MARKET_ANALYSIS"],
            data_timestamp=now,
            analysis_timestamp=now,
            signal_ttl_seconds=min(300, max(1, int((task.deadline - now).total_seconds()))),
            metadata={"handler": "TestAnalysisHandler", "test_only": True},
        )
