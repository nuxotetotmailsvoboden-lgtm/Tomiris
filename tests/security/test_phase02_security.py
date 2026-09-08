from __future__ import annotations

import pytest
from tests.support import NOW

from tomiris_agent_sdk.signing import build_signed_headers
from tomiris_common.crypto import DerivedPerAgentSecretProvider, derive_agent_secret
from tomiris_hub.core.clock import FakeClock
from tomiris_hub.core.errors import AuthenticationError
from tomiris_hub.services.authentication import AuthHeaders, HmacAuthenticator
from tomiris_orchestrator.endpoint_security import EndpointValidator
from tomiris_orchestrator.errors import EndpointSecurityError

HUB_ROOT = "hub-root-0123456789abcdef0123456789012345"  # noqa: S105
COMMAND_ROOT = "command-root-0123456789abcdef01234567890"  # noqa: S105


def test_derived_keys_isolate_agents_and_security_domains() -> None:
    agent_a = derive_agent_secret(HUB_ROOT, "TEST_AGENT_A", "hub-ingest", "current")
    agent_b = derive_agent_secret(HUB_ROOT, "TEST_AGENT_B", "hub-ingest", "current")
    command_a = derive_agent_secret(COMMAND_ROOT, "TEST_AGENT_A", "orchestrator-command", "current")
    assert agent_a != agent_b
    assert agent_a != command_a
    provider = DerivedPerAgentSecretProvider(HUB_ROOT, "current", "hub-ingest")
    assert provider.get_secret_for_agent("TEST_AGENT_A", "current") == agent_a
    assert provider.get_secret_for_agent("TEST_AGENT_B", "current") == agent_b


def test_agent_a_derived_key_cannot_impersonate_agent_b() -> None:
    provider = DerivedPerAgentSecretProvider(HUB_ROOT, "current", "hub-ingest")
    authenticator = HmacAuthenticator(provider, FakeClock(NOW), 60)
    body = b"{}"
    agent_a_key = derive_agent_secret(HUB_ROOT, "TEST_AGENT_A", "hub-ingest", "current")
    headers = build_signed_headers(
        "TEST_AGENT_B",
        "current",
        agent_a_key,
        "POST",
        "/v1/signals",
        body,
        timestamp=int(NOW.timestamp()),
    )
    auth = AuthHeaders(
        agent_id=headers["X-Tomiris-Agent-ID"],
        timestamp=headers["X-Tomiris-Timestamp"],
        nonce=headers["X-Tomiris-Nonce"],
        key_id=headers["X-Tomiris-Key-ID"],
        signature=headers["X-Tomiris-Signature"],
    )
    with pytest.raises(AuthenticationError, match="INVALID_SIGNATURE"):
        authenticator.verify("POST", "/v1/signals", auth, body)


@pytest.mark.parametrize(
    "url,environment",
    [
        ("http://agent.hf.space", "PRODUCTION"),
        ("https://user:pass@agent.hf.space", "PRODUCTION"),
        ("https://agent.hf.space/path", "PRODUCTION"),
        ("https://evil.example", "PRODUCTION"),
        ("http://10.0.0.1", "DEVELOPMENT"),
    ],
)
async def test_endpoint_policy_rejects_unsafe_urls(url: str, environment: str) -> None:
    validator = EndpointValidator(("hf.space",))
    with pytest.raises(EndpointSecurityError):
        await validator.validate(url, environment)


async def test_endpoint_policy_rejects_private_dns_in_production() -> None:
    async def private_resolver(host: str, port: int) -> list[str]:
        del host, port
        return ["127.0.0.1"]

    validator = EndpointValidator(("hf.space",), resolver=private_resolver)
    with pytest.raises(EndpointSecurityError) as captured:
        await validator.validate("https://agent.hf.space", "PRODUCTION")
    assert captured.value.code == "AGENT_ENDPOINT_FORBIDDEN"


async def test_localhost_http_is_explicitly_allowed_for_tests() -> None:
    validator = EndpointValidator(("hf.space",))
    assert await validator.validate("http://127.0.0.1:9000", "TEST") == ("http://127.0.0.1:9000")
