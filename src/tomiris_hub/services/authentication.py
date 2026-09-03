from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from tomiris_hub.core.clock import Clock
from tomiris_hub.core.errors import AuthenticationError
from tomiris_hub.core.security import (
    SecretProvider,
    body_sha256,
    canonical_request,
    constant_time_equals,
    sign_hmac,
)


@dataclass(frozen=True)
class AuthHeaders:
    agent_id: str
    timestamp: str
    nonce: str
    key_id: str
    signature: str


class HmacAuthenticator:
    def __init__(self, provider: SecretProvider, clock: Clock, max_skew_seconds: int) -> None:
        self.provider = provider
        self.clock = clock
        self.max_skew_seconds = max_skew_seconds

    def verify(self, method: str, path: str, headers: AuthHeaders, body: bytes) -> datetime:
        try:
            timestamp_int = int(headers.timestamp)
        except ValueError as exc:
            raise AuthenticationError("INVALID_TIMESTAMP", 401) from exc
        received_at = datetime.fromtimestamp(timestamp_int, tz=UTC)
        skew = abs((self.clock.now() - received_at).total_seconds())
        if skew > self.max_skew_seconds:
            raise AuthenticationError("AUTH_TIMESTAMP_OUT_OF_WINDOW", 401)
        if not headers.nonce or len(headers.nonce) < 22:
            raise AuthenticationError("INVALID_NONCE", 401)
        secret = self.provider.get_secret_for_agent(headers.agent_id, headers.key_id)
        if secret is None:
            raise AuthenticationError("UNKNOWN_KEY_ID", 401)
        canonical = canonical_request(
            method,
            path,
            headers.agent_id,
            headers.timestamp,
            headers.nonce,
            headers.key_id,
            body_sha256(body),
        )
        expected = sign_hmac(secret, canonical)
        if not constant_time_equals(expected, headers.signature):
            raise AuthenticationError("INVALID_SIGNATURE", 401)
        return received_at
