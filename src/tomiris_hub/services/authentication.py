from __future__ import annotations

import re
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
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", headers.agent_id):
            raise AuthenticationError("MALFORMED_AGENT_ID", 401)
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", headers.key_id):
            raise AuthenticationError("MALFORMED_KEY_ID", 401)
        if not re.fullmatch(r"[A-Za-z0-9_-]{22,256}", headers.nonce):
            raise AuthenticationError("INVALID_NONCE", 401)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", headers.signature):
            raise AuthenticationError("MALFORMED_SIGNATURE", 401)
        if not re.fullmatch(r"-?[0-9]{1,20}", headers.timestamp):
            raise AuthenticationError("INVALID_TIMESTAMP", 401)
        try:
            timestamp_int = int(headers.timestamp)
            received_at = datetime.fromtimestamp(timestamp_int, tz=UTC)
        except (ValueError, OverflowError, OSError) as exc:
            raise AuthenticationError("INVALID_TIMESTAMP", 401) from exc
        delta = (self.clock.now() - received_at).total_seconds()
        if delta > self.max_skew_seconds:
            raise AuthenticationError("AUTH_TIMESTAMP_TOO_OLD", 401)
        if delta < -self.max_skew_seconds:
            raise AuthenticationError("AUTH_TIMESTAMP_IN_FUTURE", 401)
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
