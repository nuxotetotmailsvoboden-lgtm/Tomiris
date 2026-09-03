from datetime import UTC, datetime

import pytest

from tomiris_agent_sdk.signing import build_signed_headers
from tomiris_hub.core.clock import FakeClock
from tomiris_hub.core.errors import AuthenticationError
from tomiris_hub.core.security import SharedSecretProvider
from tomiris_hub.services.authentication import AuthHeaders, HmacAuthenticator


def test_changed_raw_body_is_rejected() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    secret = "a" * 32
    headers = build_signed_headers(
        "TEST_AGENT_001",
        "current",
        secret,
        "POST",
        "/v1/signals",
        b'{"a":1}',
        timestamp=int(now.timestamp()),
    )
    auth = HmacAuthenticator(SharedSecretProvider("current", secret), FakeClock(now), 60)
    with pytest.raises(AuthenticationError, match="INVALID_SIGNATURE"):
        auth.verify(
            "POST",
            "/v1/signals",
            AuthHeaders(
                agent_id=headers["X-Tomiris-Agent-ID"],
                timestamp=headers["X-Tomiris-Timestamp"],
                nonce=headers["X-Tomiris-Nonce"],
                key_id=headers["X-Tomiris-Key-ID"],
                signature=headers["X-Tomiris-Signature"],
            ),
            b'{"a":2}',
        )
