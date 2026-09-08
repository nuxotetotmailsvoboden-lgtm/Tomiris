from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import ValidationError as PydanticValidationError

from tomiris_agent_runtime.config import AgentRuntimeSettings
from tomiris_agent_runtime.handler import AnalysisHandler, TestAnalysisHandler
from tomiris_agent_runtime.request_body import read_limited_task_body
from tomiris_agent_runtime.security import CommandAuthenticator, CommandAuthHeaders
from tomiris_agent_runtime.sink import HubSignalSink, SignalSink
from tomiris_agent_runtime.state import RuntimeTaskStore
from tomiris_agent_sdk.client import HubClient
from tomiris_core_contracts.orchestration import (
    AnalysisTaskAck,
    AnalysisTaskRequest,
    RuntimeCapabilities,
)
from tomiris_hub.core.clock import Clock, SystemClock
from tomiris_hub.core.errors import HubError, ValidationError
from tomiris_hub.core.security import body_sha256

logger = logging.getLogger(__name__)

_COMMAND_HEADERS = {
    "orchestrator_id": "X-Tomiris-Orchestrator-ID",
    "timestamp": "X-Tomiris-Timestamp",
    "nonce": "X-Tomiris-Nonce",
    "key_id": "X-Tomiris-Key-ID",
    "signature": "X-Tomiris-Signature",
}


def create_agent_runtime_app(
    settings: AgentRuntimeSettings,
    *,
    handler: AnalysisHandler | None = None,
    sink: SignalSink | None = None,
    clock: Clock | None = None,
    task_store: RuntimeTaskStore | None = None,
) -> FastAPI:
    active_clock = clock or SystemClock()
    active_handler = handler or TestAnalysisHandler(active_clock)
    active_sink = sink or HubSignalSink(
        HubClient(
            settings.tomiris_hub_url,
            settings.tomiris_agent_id,
            settings.tomiris_hub_key_id,
            settings.tomiris_hub_agent_secret.get_secret_value(),
        )
    )
    active_store = task_store or RuntimeTaskStore()
    authenticator = CommandAuthenticator(
        settings.tomiris_orchestrator_id,
        settings.tomiris_agent_id,
        settings.tomiris_orchestrator_command_key_id,
        settings.tomiris_orchestrator_command_secret.get_secret_value(),
        active_clock,
        settings.command_max_clock_skew_seconds,
    )
    app = FastAPI(title="TOMIRIS Universal Agent Runtime", version=settings.runtime_version)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live", "agent_id": settings.tomiris_agent_id}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready", "agent_id": settings.tomiris_agent_id}

    @app.get("/v1/capabilities")
    async def capabilities() -> RuntimeCapabilities:
        return RuntimeCapabilities(
            agent_id=settings.tomiris_agent_id,
            runtime_version=settings.runtime_version,
            role=settings.tomiris_agent_role,
            capabilities=list(settings.capabilities),
            supported_assets=list(settings.supported_assets),
            protocol_versions=["1.0"],
        )

    async def execute(task: AnalysisTaskRequest) -> None:
        try:
            signal = await active_handler.analyze(task)
            sent = await active_sink.send(signal)
            if not sent:
                logger.error(
                    "agent_signal_delivery_failed",
                    extra={
                        "task_id": str(task.task_id),
                        "agent_id": task.agent_id,
                        "snapshot_id": str(task.snapshot_id),
                        "correlation_id": str(task.correlation_id),
                        "reason_code": "HUB_SIGNAL_REJECTED",
                    },
                )
        except Exception:
            logger.exception(
                "agent_analysis_execution_failed",
                extra={
                    "task_id": str(task.task_id),
                    "agent_id": task.agent_id,
                    "snapshot_id": str(task.snapshot_id),
                    "correlation_id": str(task.correlation_id),
                    "reason_code": "TEST_HANDLER_FAILURE",
                },
            )

    @app.post("/v1/analyze", status_code=202, response_model=AnalysisTaskAck)
    async def analyze(request: Request, background_tasks: BackgroundTasks) -> AnalysisTaskAck:
        try:
            body = await read_limited_task_body(request, settings.max_task_request_bytes)
            values = {key: request.headers.get(name) for key, name in _COMMAND_HEADERS.items()}
            if any(value is None for value in values.values()):
                raise ValidationError("MISSING_COMMAND_AUTH_HEADERS", 401)
            auth = CommandAuthHeaders(**values)  # type: ignore[arg-type]
            authenticator.verify(auth, body)
            task = AnalysisTaskRequest.model_validate_json(body)
            if task.agent_id != settings.tomiris_agent_id:
                raise ValidationError("TASK_AGENT_MISMATCH", 403)
            if task.deadline <= active_clock.now():
                raise ValidationError("TASK_EXPIRED", 422)
            if task.required_capability not in settings.capabilities:
                raise ValidationError("AGENT_CAPABILITY_MISMATCH", 422)
            if task.asset not in settings.supported_assets:
                raise ValidationError("AGENT_ASSET_MISMATCH", 422)
            ack = AnalysisTaskAck(
                task_id=task.task_id,
                agent_id=settings.tomiris_agent_id,
                accepted_at=active_clock.now(),
                runtime_version=settings.runtime_version,
            )
            accepted_ack, is_new = await active_store.accept(
                nonce=auth.nonce,
                nonce_expires_at=active_clock.now()
                + timedelta(seconds=settings.command_nonce_ttl_seconds),
                now=active_clock.now(),
                task_id=task.task_id,
                body_hash=body_sha256(body),
                ack=ack,
            )
            if is_new:
                background_tasks.add_task(execute, task)
            return accepted_ack
        except PydanticValidationError:
            raise HTTPException(
                status_code=422, detail={"code": "INVALID_TASK_SCHEMA", "request_id": str(uuid4())}
            ) from None
        except HubError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "request_id": str(uuid4())},
            ) from None

    return app
