from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Protocol


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_request(
    method: str, path: str, agent_id: str, timestamp: str, nonce: str, key_id: str, body_hash: str
) -> str:
    return "\n".join((method.upper(), path, agent_id, timestamp, nonce, key_id, body_hash))


def sign_hmac(secret: str, canonical: str) -> str:
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    try:
        return hmac.compare_digest(left.encode("ascii"), right.encode("ascii"))
    except UnicodeEncodeError:
        return False


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)


class SecretProvider(Protocol):
    def get_secret_for_agent(self, agent_id: str, key_id: str) -> str | None: ...


@dataclass(frozen=True)
class SharedSecretProvider:
    current_key_id: str
    current_secret: str
    previous_key_id: str | None = None
    previous_secret: str | None = None

    def get_secret_for_agent(self, agent_id: str, key_id: str) -> str | None:
        del agent_id
        if key_id == self.current_key_id:
            return self.current_secret
        if self.previous_key_id and self.previous_secret and key_id == self.previous_key_id:
            return self.previous_secret
        return None
