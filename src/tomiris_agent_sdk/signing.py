from __future__ import annotations

import time

from tomiris_hub.core.security import body_sha256, canonical_request, generate_nonce, sign_hmac


def build_signed_headers(
    agent_id: str,
    key_id: str,
    secret: str,
    method: str,
    path: str,
    body: bytes,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    current_timestamp = timestamp if timestamp is not None else int(time.time())
    current_nonce = nonce or generate_nonce()
    canonical = canonical_request(
        method, path, agent_id, str(current_timestamp), current_nonce, key_id, body_sha256(body)
    )
    return {
        "X-Tomiris-Agent-ID": agent_id,
        "X-Tomiris-Timestamp": str(current_timestamp),
        "X-Tomiris-Nonce": current_nonce,
        "X-Tomiris-Key-ID": key_id,
        "X-Tomiris-Signature": sign_hmac(secret, canonical),
        "Content-Type": "application/json",
    }
