from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from tomiris_hub.core.clock import Clock
from tomiris_hub.core.errors import AuthenticationError
from tomiris_hub.core.security import body_sha256, constant_time_equals, generate_nonce, sign_hmac


def canonical_command(
    method: str,
    path: str,
    orchestrator_id: str,
    target_agent_id: str,
    timestamp: str,
    nonce: str,
    key_id: str,
    body_hash: str,
) -> str:
    return "\n".join(
        (
            method.upper(),
            path,
            orchestrator_id,
            target_agent_id,
            timestamp,
            nonce,
            key_id,
            body_hash,
        )
    )


def build_command_headers(
    orchestrator_id: str,
    target_agent_id: str,
    key_id: str,
    secret: str,
    body: bytes,
    *,
    timestamp: int,
    nonce: str | None = None,
) -> dict[str, str]:
    timestamp_value = str(timestamp)
    nonce_value = nonce or generate_nonce()
    canonical = canonical_command(
        "POST",
        "/v1/analyze",
        orchestrator_id,
        target_agent_id,
        timestamp_value,
        nonce_value,
        key_id,
        body_sha256(body),
    )
    return {
        "X-Tomiris-Orchestrator-ID": orchestrator_id,
        "X-Tomiris-Timestamp": timestamp_value,
        "X-Tomiris-Nonce": nonce_value,
        "X-Tomiris-Key-ID": key_id,
        "X-Tomiris-Signature": sign_hmac(secret, canonical),
        "Content-Type": "application/json",
    }


@dataclass(frozen=True)
class CommandAuthHeaders:
    orchestrator_id: str
    timestamp: str
    nonce: str
    key_id: str
    signature: str


class CommandAuthenticator:
    def __init__(
        self,
        orchestrator_id: str,
        target_agent_id: str,
        key_id: str,
        secret: str,
        clock: Clock,
        max_skew_seconds: int,
    ) -> None:
        self.orchestrator_id = orchestrator_id
        self.target_agent_id = target_agent_id
        self.key_id = key_id
        self.secret = secret
        self.clock = clock
        self.max_skew_seconds = max_skew_seconds

    def verify(self, headers: CommandAuthHeaders, body: bytes) -> None:
        if headers.orchestrator_id != self.orchestrator_id:
            raise AuthenticationError("ORCHESTRATOR_ID_MISMATCH", 401)
        if headers.key_id != self.key_id:
            raise AuthenticationError("UNKNOWN_COMMAND_KEY_ID", 401)
        if not re.fullmatch(r"[A-Za-z0-9_-]{22,256}", headers.nonce):
            raise AuthenticationError("INVALID_COMMAND_NONCE", 401)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", headers.signature):
            raise AuthenticationError("MALFORMED_COMMAND_SIGNATURE", 401)
        if not re.fullmatch(r"-?[0-9]{1,20}", headers.timestamp):
            raise AuthenticationError("INVALID_COMMAND_TIMESTAMP", 401)
        try:
            timestamp = datetime.fromtimestamp(int(headers.timestamp), tz=UTC)
        except (ValueError, OverflowError, OSError) as exc:
            raise AuthenticationError("INVALID_COMMAND_TIMESTAMP", 401) from exc
        delta = (self.clock.now() - timestamp).total_seconds()
        if delta > self.max_skew_seconds:
            raise AuthenticationError("COMMAND_EXPIRED", 401)
        if delta < -self.max_skew_seconds:
            raise AuthenticationError("COMMAND_TIMESTAMP_IN_FUTURE", 401)
        expected = sign_hmac(
            self.secret,
            canonical_command(
                "POST",
                "/v1/analyze",
                headers.orchestrator_id,
                self.target_agent_id,
                headers.timestamp,
                headers.nonce,
                headers.key_id,
                body_sha256(body),
            ),
        )
        if not constant_time_equals(expected, headers.signature):
            raise AuthenticationError("INVALID_COMMAND_SIGNATURE", 401)
