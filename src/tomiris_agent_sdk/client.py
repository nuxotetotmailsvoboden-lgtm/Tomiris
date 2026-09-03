from __future__ import annotations

import json

import httpx

from tomiris_agent_sdk.signing import build_signed_headers


class HubClient:
    def __init__(self, base_url: str, agent_id: str, key_id: str, secret: str) -> None:
        self.base_url, self.agent_id, self.key_id, self.secret = (
            base_url.rstrip("/"),
            agent_id,
            key_id,
            secret,
        )

    async def send_signal(self, payload: dict[str, object]) -> httpx.Response:
        path = "/v1/signals"
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = build_signed_headers(self.agent_id, self.key_id, self.secret, "POST", path, body)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            return await client.post(path, content=body, headers=headers)
