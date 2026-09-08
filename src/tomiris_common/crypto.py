from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass


def hkdf_sha256(
    input_key_material: bytes,
    *,
    salt: bytes,
    info: bytes,
    length: int = 32,
) -> bytes:
    """RFC 5869 HKDF-SHA256 with an explicit domain-separated salt/info."""

    if not input_key_material:
        raise ValueError("input key material must not be empty")
    if length < 1 or length > 255 * hashlib.sha256().digest_size:
        raise ValueError("invalid HKDF output length")
    pseudo_random_key = hmac.new(salt, input_key_material, hashlib.sha256).digest()
    output = bytearray()
    previous = b""
    counter = 1
    while len(output) < length:
        previous = hmac.new(
            pseudo_random_key,
            previous + info + bytes([counter]),
            hashlib.sha256,
        ).digest()
        output.extend(previous)
        counter += 1
    return bytes(output[:length])


def derive_agent_secret(master_secret: str, agent_id: str, purpose: str, key_id: str) -> str:
    if purpose not in {"hub-ingest", "orchestrator-command"}:
        raise ValueError("unsupported credential purpose")
    if len(master_secret) < 32:
        raise ValueError("master secret must contain at least 32 characters")
    info = f"tomiris:v1:{purpose}:{agent_id}:{key_id}".encode()
    derived = hkdf_sha256(
        master_secret.encode(),
        salt=b"tomiris-derived-agent-secret-v1",
        info=info,
    )
    return base64.urlsafe_b64encode(derived).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class DerivedPerAgentSecretProvider:
    master_secret: str
    current_key_id: str
    purpose: str
    previous_master_secret: str | None = None
    previous_key_id: str | None = None

    def get_secret_for_agent(self, agent_id: str, key_id: str) -> str | None:
        if key_id == self.current_key_id:
            return derive_agent_secret(self.master_secret, agent_id, self.purpose, key_id)
        if self.previous_key_id and self.previous_master_secret and key_id == self.previous_key_id:
            return derive_agent_secret(
                self.previous_master_secret,
                agent_id,
                self.purpose,
                key_id,
            )
        return None
