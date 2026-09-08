from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from tomiris_agent_runtime.application import create_agent_runtime_app
from tomiris_agent_runtime.config import AgentRuntimeSettings
from tomiris_agent_runtime.handler import TestAnalysisHandler
from tomiris_agent_runtime.sink import SignalSink
from tomiris_hub.core.clock import Clock


@dataclass(frozen=True)
class TestRuntimeBehaviour:
    response_delay_seconds: float = 0.0
    analysis_delay_seconds: float = 0.0
    forced_status: int | None = None


def create_test_runtime_app(
    settings: AgentRuntimeSettings,
    *,
    clock: Clock,
    sink: SignalSink,
    behaviour: TestRuntimeBehaviour | None = None,
) -> FastAPI:
    """Fixture-only behaviours for local protocol and failure tests."""

    active_behaviour = behaviour or TestRuntimeBehaviour()
    runtime = create_agent_runtime_app(
        settings,
        clock=clock,
        sink=sink,
        handler=TestAnalysisHandler(clock, delay_seconds=active_behaviour.analysis_delay_seconds),
    )
    harness = FastAPI(title="TOMIRIS Phase 02 local harness")

    @harness.middleware("http")
    async def simulate(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/v1/analyze":
            if active_behaviour.response_delay_seconds:
                await asyncio.sleep(active_behaviour.response_delay_seconds)
            if active_behaviour.forced_status is not None:
                return Response(status_code=active_behaviour.forced_status)
        return await call_next(request)

    harness.mount("/", runtime)
    return harness
