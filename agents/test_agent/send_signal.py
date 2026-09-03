from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from tomiris_agent_sdk.client import HubClient


async def main() -> None:
    snapshot_id = UUID(os.environ["TOMIRIS_TEST_SNAPSHOT_ID"])
    now = datetime.now(UTC).isoformat()
    payload: dict[str, object] = {
        "protocol_version": "1.0",
        "message_id": str(uuid4()),
        "agent_id": "TEST_AGENT_001",
        "agent_run_id": str(uuid4()),
        "snapshot_id": str(snapshot_id),
        "asset": "TEST",
        "bias": "NEUTRAL",
        "confidence": 50,
        "impact": 0,
        "time_horizon": "test",
        "evidence": [
            {
                "evidence_type": "test",
                "summary": "Phase 01 signed integration smoke signal",
                "source_type": "test",
                "source_id": "TEST_AGENT_001",
                "observed_at": now,
                "source_timestamp": now,
                "metadata": {},
            }
        ],
        "risk_flags": [],
        "data_timestamp": now,
        "analysis_timestamp": now,
        "signal_ttl_seconds": 60,
        "metadata": {"phase": "01"},
    }
    client = HubClient(
        os.getenv("TOMIRIS_HUB_URL", "http://127.0.0.1:8000"),
        "TEST_AGENT_001",
        os.environ["TOMIRIS_HUB_INGEST_KEY_ID"],
        os.environ["TOMIRIS_HUB_INGEST_SECRET"],
    )
    response = await client.send_signal(payload)
    print(response.status_code, response.text)


if __name__ == "__main__":
    asyncio.run(main())
