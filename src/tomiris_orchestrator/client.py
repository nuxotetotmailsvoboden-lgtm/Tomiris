from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

import httpx

from tomiris_agent_runtime.security import build_command_headers
from tomiris_core_contracts.orchestration import AnalysisTaskAck, AnalysisTaskRequest
from tomiris_hub.core.security import SecretProvider
from tomiris_orchestrator.endpoint_security import EndpointValidator
from tomiris_orchestrator.errors import EndpointSecurityError


class DispatchDisposition(StrEnum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RETRYABLE = "RETRYABLE"
    PERMANENT = "PERMANENT"


@dataclass(frozen=True)
class DispatchCommand:
    task_id: UUID
    orchestration_run_id: UUID
    snapshot_id: UUID
    agent_id: str
    asset: str
    required_capability: str
    priority: int
    created_at: datetime
    signal_deadline: datetime
    correlation_id: UUID
    causation_id: UUID | None
    context: dict[str, object]
    endpoint_url: str
    endpoint_environment: str


@dataclass(frozen=True)
class DispatchResult:
    disposition: DispatchDisposition
    error_code: str | None = None
    ack: AnalysisTaskAck | None = None
    latency_ms: float | None = None


class AgentDispatchClient:
    def __init__(
        self,
        *,
        orchestrator_id: str,
        command_key_id: str,
        secret_provider: SecretProvider,
        endpoint_validator: EndpointValidator,
        connect_timeout_seconds: float,
        ack_timeout_seconds: float,
        cold_start_grace_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.orchestrator_id = orchestrator_id
        self.command_key_id = command_key_id
        self.secret_provider = secret_provider
        self.endpoint_validator = endpoint_validator
        self.timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=ack_timeout_seconds + cold_start_grace_seconds,
            write=ack_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._client = http_client

    async def dispatch(self, command: DispatchCommand, timestamp: int) -> DispatchResult:
        try:
            endpoint = await self.endpoint_validator.validate(
                command.endpoint_url, command.endpoint_environment
            )
        except EndpointSecurityError as error:
            return DispatchResult(DispatchDisposition.PERMANENT, error.code)
        secret = self.secret_provider.get_secret_for_agent(command.agent_id, self.command_key_id)
        if secret is None:
            return DispatchResult(DispatchDisposition.PERMANENT, "AGENT_AUTH_FAILED")
        request = AnalysisTaskRequest(
            protocol_version="1.0",
            task_id=command.task_id,
            orchestration_run_id=command.orchestration_run_id,
            snapshot_id=command.snapshot_id,
            agent_id=command.agent_id,
            asset=command.asset,
            required_capability=command.required_capability,
            priority=command.priority,
            created_at=command.created_at,
            deadline=command.signal_deadline,
            correlation_id=command.correlation_id,
            causation_id=command.causation_id,
            context=command.context,
        )
        body = request.model_dump_json().encode("utf-8")
        headers = build_command_headers(
            self.orchestrator_id,
            command.agent_id,
            self.command_key_id,
            secret,
            body,
            timestamp=timestamp,
        )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        started = datetime.now().timestamp()
        try:
            response = await client.post(f"{endpoint}/v1/analyze", content=body, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError):
            return DispatchResult(DispatchDisposition.RETRYABLE, "AGENT_ACK_TIMEOUT")
        finally:
            if owns_client:
                await client.aclose()
        latency = max(0.0, (datetime.now().timestamp() - started) * 1000)
        if response.status_code == 202:
            try:
                ack = AnalysisTaskAck.model_validate(response.json())
            except (ValueError, TypeError):
                return DispatchResult(
                    DispatchDisposition.PERMANENT, "AGENT_INVALID_ACK", latency_ms=latency
                )
            if ack.task_id != command.task_id or ack.agent_id != command.agent_id:
                return DispatchResult(
                    DispatchDisposition.PERMANENT, "AGENT_INVALID_ACK", latency_ms=latency
                )
            return DispatchResult(DispatchDisposition.ACKNOWLEDGED, ack=ack, latency_ms=latency)
        if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
            return DispatchResult(
                DispatchDisposition.RETRYABLE,
                f"AGENT_HTTP_{response.status_code}",
                latency_ms=latency,
            )
        error_code = "AGENT_AUTH_FAILED" if response.status_code in {401, 403} else "AGENT_REJECTED"
        return DispatchResult(DispatchDisposition.PERMANENT, error_code, latency_ms=latency)
