from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from tests.support import NOW

from tomiris_common.crypto import DerivedPerAgentSecretProvider
from tomiris_orchestrator.client import (
    AgentDispatchClient,
    DispatchCommand,
    DispatchDisposition,
)
from tomiris_orchestrator.endpoint_security import EndpointValidator

COMMAND_ROOT = "dispatch-command-root-0123456789abcdef012345"  # noqa: S105


def command() -> DispatchCommand:
    return DispatchCommand(
        task_id=uuid4(),
        orchestration_run_id=uuid4(),
        snapshot_id=uuid4(),
        agent_id="TEST_AGENT_A",
        asset="TEST",
        required_capability="test.echo",
        priority=50,
        created_at=NOW,
        signal_deadline=NOW + timedelta(minutes=1),
        correlation_id=uuid4(),
        causation_id=None,
        context={},
        endpoint_url="http://localhost",
        endpoint_environment="TEST",
    )


def client(handler: httpx.AsyncBaseTransport) -> AgentDispatchClient:
    return AgentDispatchClient(
        orchestrator_id="ORCHESTRATOR_TEST",
        command_key_id="current",
        secret_provider=DerivedPerAgentSecretProvider(
            COMMAND_ROOT, "current", "orchestrator-command"
        ),
        endpoint_validator=EndpointValidator(("hf.space",)),
        connect_timeout_seconds=1,
        ack_timeout_seconds=1,
        cold_start_grace_seconds=1,
        http_client=httpx.AsyncClient(transport=handler),
    )


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_retryable_http_statuses(status: int) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request)

    result = await client(httpx.MockTransport(respond)).dispatch(command(), int(NOW.timestamp()))
    assert result.disposition == DispatchDisposition.RETRYABLE


@pytest.mark.parametrize("status", [400, 401, 403, 422])
async def test_permanent_http_statuses_are_not_blindly_retried(status: int) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request)

    result = await client(httpx.MockTransport(respond)).dispatch(command(), int(NOW.timestamp()))
    assert result.disposition == DispatchDisposition.PERMANENT


async def test_valid_ack_and_timeout_classification() -> None:
    dispatch_command = command()

    async def acknowledge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            request=request,
            json={
                "task_id": str(dispatch_command.task_id),
                "agent_id": dispatch_command.agent_id,
                "status": "ACKNOWLEDGED",
                "accepted_at": NOW.isoformat(),
                "runtime_version": "0.2.0",
            },
        )

    accepted = await client(httpx.MockTransport(acknowledge)).dispatch(
        dispatch_command, int(NOW.timestamp())
    )
    assert accepted.disposition == DispatchDisposition.ACKNOWLEDGED

    async def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("cold start", request=request)

    timed_out = await client(httpx.MockTransport(timeout)).dispatch(
        dispatch_command, int(NOW.timestamp())
    )
    assert timed_out.disposition == DispatchDisposition.RETRYABLE
    assert timed_out.error_code == "AGENT_ACK_TIMEOUT"
