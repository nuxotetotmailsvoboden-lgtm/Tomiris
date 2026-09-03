from tomiris_hub.core.security import (
    body_sha256,
    canonical_request,
    constant_time_equals,
    generate_nonce,
    sign_hmac,
)


def test_hmac_changes_when_body_changes() -> None:
    canonical = canonical_request(
        "POST", "/v1/signals", "TEST_AGENT_001", "1", "a" * 22, "current", body_sha256(b'{"a":1}')
    )
    signature = sign_hmac("x" * 32, canonical)
    changed = canonical_request(
        "POST", "/v1/signals", "TEST_AGENT_001", "1", "a" * 22, "current", body_sha256(b'{"a":2}')
    )
    assert not constant_time_equals(signature, sign_hmac("x" * 32, changed))


def test_nonce_has_sufficient_length() -> None:
    assert len(generate_nonce()) >= 43
