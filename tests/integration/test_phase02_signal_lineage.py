from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from tests.conftest import DatabaseHarness
from tests.support import (
    INCOMPATIBLE_SNAPSHOT_ID,
    NOW,
    VALID_SNAPSHOT_ID,
    encode_payload,
    hub_client,
    reason_code,
    signal_payload,
    signed_headers,
)

from tomiris_hub.database.models import Agent, AgentTask, OrchestrationRun, Signal


async def seed_task(
    database: DatabaseHarness,
    *,
    status: str = "WAITING_SIGNAL",
    deadline_offset: int = 60,
) -> tuple[UUID, UUID]:
    run_id, task_id = uuid4(), uuid4()
    async with database.session_factory() as session, session.begin():
        session.add(
            OrchestrationRun(
                orchestration_run_id=run_id,
                snapshot_id=VALID_SNAPSHOT_ID,
                asset="TEST",
                trigger_type="TEST",
                status="COLLECTING",
                outcome=None,
                created_at=NOW - timedelta(seconds=10),
                started_at=NOW - timedelta(seconds=10),
                collection_deadline=NOW + timedelta(minutes=2),
                completed_at=None,
                correlation_id=uuid4(),
                policy_version="test",
                metadata_json={},
            )
        )
        await session.flush()
        session.add(
            AgentTask(
                task_id=task_id,
                orchestration_run_id=run_id,
                snapshot_id=VALID_SNAPSHOT_ID,
                agent_id="TEST_AGENT_001",
                asset="TEST",
                required_capability="signal_ingestion",
                required=True,
                priority=50,
                criticality="NORMAL",
                status=status,
                attempt_count=1,
                dispatch_after=NOW - timedelta(seconds=10),
                dispatch_deadline=NOW + timedelta(seconds=min(30, deadline_offset)),
                signal_deadline=NOW + timedelta(seconds=deadline_offset),
                context_json={},
                created_at=NOW - timedelta(seconds=10),
                updated_at=NOW - timedelta(seconds=5),
            )
        )
    return run_id, task_id


async def post_task_signal(
    client: httpx.AsyncClient,
    run_id: UUID,
    task_id: UUID,
    **changes: object,
) -> httpx.Response:
    payload = signal_payload(task_id=str(task_id), orchestration_run_id=str(run_id))
    payload.update(changes)
    body = encode_payload(payload)
    agent_id = str(payload["agent_id"])
    return await client.post(
        "/v1/signals", content=body, headers=signed_headers(body, agent_id=agent_id)
    )


async def test_task_signal_is_persisted_and_completes_task_atomically(
    clean_database: DatabaseHarness,
) -> None:
    run_id, task_id = await seed_task(clean_database)
    async with hub_client(clean_database.url) as client:
        response = await post_task_signal(client, run_id, task_id)
    assert response.status_code == 202
    async with clean_database.session_factory() as session:
        task = await session.get(AgentTask, task_id)
        signal = await session.get(Signal, UUID(response.json()["message_id"]))
        assert task is not None and signal is not None
        assert task.status == "SIGNAL_RECEIVED"
        assert signal.task_id == task_id


async def test_task_signal_rejects_wrong_agent_snapshot_and_asset(
    clean_database: DatabaseHarness,
) -> None:
    run_id, task_id = await seed_task(clean_database)
    async with clean_database.session_factory() as session, session.begin():
        test_agent = await session.get(Agent, "TEST_AGENT_001")
        assert test_agent is not None
        test_agent.supported_assets = ["TEST", "OTHER"]
    async with hub_client(clean_database.url) as client:
        wrong_agent = await post_task_signal(client, run_id, task_id, agent_id="OTHER_AGENT_001")
        wrong_snapshot = await post_task_signal(
            client, run_id, task_id, snapshot_id=str(INCOMPATIBLE_SNAPSHOT_ID)
        )
        wrong_asset = await post_task_signal(client, run_id, task_id, asset="OTHER")
    assert reason_code(wrong_agent) == "TASK_AGENT_MISMATCH"
    assert reason_code(wrong_snapshot) == "TASK_SNAPSHOT_MISMATCH"
    assert reason_code(wrong_asset) == "TASK_ASSET_MISMATCH"


async def test_duplicate_and_late_task_results_are_rejected(
    clean_database: DatabaseHarness,
) -> None:
    run_id, task_id = await seed_task(clean_database)
    async with hub_client(clean_database.url) as client:
        accepted = await post_task_signal(client, run_id, task_id)
        duplicate = await post_task_signal(client, run_id, task_id)
    assert accepted.status_code == 202
    assert duplicate.status_code == 409
    assert reason_code(duplicate) == "DUPLICATE_TASK_RESULT"

    late_run_id, late_task_id = await seed_task(clean_database, deadline_offset=0)
    async with hub_client(clean_database.url) as client:
        late = await post_task_signal(client, late_run_id, late_task_id)
    assert late.status_code == 422
    assert reason_code(late) == "TASK_EXPIRED"
