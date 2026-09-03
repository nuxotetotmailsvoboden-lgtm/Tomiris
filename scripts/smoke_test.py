"""Manual Phase 01 smoke test: valid signal, replay and wrong-secret rejection."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from tomiris_agent_sdk.signing import build_signed_headers


async def main() -> None:
    snapshot_id = UUID(os.environ["TOMIRIS_TEST_SNAPSHOT_ID"])
    base_url = os.getenv("TOMIRIS_HUB_URL", "http://127.0.0.1:8000")
    secret = os.environ["TOMIRIS_HUB_INGEST_SECRET"]
    now = datetime.now(UTC).isoformat()
    payload = {
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
        "evidence": [],
        "risk_flags": [],
        "data_timestamp": now,
        "analysis_timestamp": now,
        "signal_ttl_seconds": 60,
        "metadata": {},
    }
    path = "/v1/signals"
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = build_signed_headers("TEST_AGENT_001", "current", secret, "POST", path, body)
    async with httpx.AsyncClient(base_url=base_url) as client:
        for label, request_headers in (
            ("valid", headers),
            ("replay", headers),
            (
                "wrong-secret",
                build_signed_headers("TEST_AGENT_001", "current", "wrong" * 8, "POST", path, body),
            ),
        ):
            response = await client.post(path, content=body, headers=request_headers)
            print(label, response.status_code, response.text)


if __name__ == "__main__":
    asyncio.run(main())
