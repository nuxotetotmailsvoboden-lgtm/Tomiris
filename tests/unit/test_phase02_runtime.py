from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import httpx
from tests.support import NOW

from tomiris_agent_runtime.application import create_agent_runtime_app
from tomiris_agent_runtime.config import AgentRuntimeSettings
from tomiris_agent_runtime.security import build_command_headers
from tomiris_agent_runtime.sink import NullSignalSink
from tomiris_core_contracts.orchestration import AnalysisTaskRequest
from tomiris_hub.core.clock import FakeClock

COMMAND_SECRET = "command-root-0123456789abcdef0123456789"  # noqa: S105
INGEST_SECRET = "ingest-root-0123456789abcdef01234567890"  # noqa: S105


def runtime_settings() -> AgentRuntimeSettings:
    return AgentRuntimeSettings(
        _env_file=None,
        tomiris_agent_id="TEST_AGENT_A",
        tomiris_agent_role="test",
        tomiris_agent_capabilities="test.echo",
        tomiris_agent_supported_assets="TEST",
        tomiris_hub_url="http://localhost:8000",
        tomiris_hub_agent_secret=INGEST_SECRET,
        tomiris_orchestrator_id="ORCHESTRATOR_TEST",
        tomiris_orchestrator_command_secret=COMMAND_SECRET,
    )


def task_request(**changes: object) -> AnalysisTaskRequest:
    values: dict[str, object] = {
        "protocol_version": "1.0",
        "task_id": uuid4(),
        "orchestration_run_id": uuid4(),
        "snapshot_id": uuid4(),
        "agent_id": "TEST_AGENT_A",
        "asset": "TEST",
        "required_capability": "test.echo",
        "priority": 50,
        "created_at": NOW,
        "deadline": NOW + timedelta(minutes=1),
        "correlation_id": uuid4(),
        "context": {"bounded": True},
    }
    values.update(changes)
    return AnalysisTaskRequest.model_validate(values)


async def send(
    client: httpx.AsyncClient,
    task: AnalysisTaskRequest,
    *,
    secret: str = COMMAND_SECRET,
    nonce: str | None = None,
) -> httpx.Response:
    body = task.model_dump_json().encode()
    headers = build_command_headers(
        "ORCHESTRATOR_TEST",
        "TEST_AGENT_A",
        "current",
        secret,
        body,
        timestamp=int(NOW.timestamp()),
        nonce=nonce,
    )
    return await client.post("/v1/analyze", content=body, headers=headers)


async def test_runtime_ack_is_async_contract_and_duplicate_task_is_safe() -> None:
    app = create_agent_runtime_app(runtime_settings(), clock=FakeClock(NOW), sink=NullSignalSink())
    task = task_request()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime"
    ) as client:
        response = await send(client, task)
        duplicate = await send(client, task)
        capabilities = await client.get("/v1/capabilities")
    assert response.status_code == 202
    assert response.json()["status"] == "ACKNOWLEDGED"
    assert "analysis" not in response.json()
    assert duplicate.status_code == 202
    assert duplicate.json() == response.json()
    assert capabilities.json()["capabilities"] == ["test.echo"]


async def test_runtime_rejects_auth_agent_capability_and_expiry() -> None:
    app = create_agent_runtime_app(runtime_settings(), clock=FakeClock(NOW), sink=NullSignalSink())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime"
    ) as client:
        wrong_hmac = await send(client, task_request(), secret="x" * 32)
        wrong_agent = await send(client, task_request(agent_id="OTHER_AGENT_A"))
        wrong_capability = await send(client, task_request(required_capability="admin"))
        expired = await send(
            client,
            task_request(
                created_at=NOW - timedelta(minutes=2), deadline=NOW - timedelta(minutes=1)
            ),
        )
    assert wrong_hmac.status_code == 401
    assert wrong_agent.status_code == 403
    assert wrong_capability.status_code == 422
    assert expired.status_code == 422


async def test_runtime_nonce_replay_is_rejected() -> None:
    app = create_agent_runtime_app(runtime_settings(), clock=FakeClock(NOW), sink=NullSignalSink())
    task = task_request()
    nonce = "A" * 32
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime"
    ) as client:
        first = await send(client, task, nonce=nonce)
        replay = await send(client, task, nonce=nonce)
    assert first.status_code == 202
    assert replay.status_code == 409
