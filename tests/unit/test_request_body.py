from __future__ import annotations

import pytest
from starlette.requests import Request

from tomiris_hub.core.errors import ValidationError
from tomiris_hub.core.request_body import read_limited_body


def _request(chunks: list[bytes], content_length: str | None = None) -> Request:
    pending = list(chunks)

    async def receive() -> dict[str, object]:
        body = pending.pop(0) if pending else b""
        return {"type": "http.request", "body": body, "more_body": bool(pending)}

    headers = [] if content_length is None else [(b"content-length", content_length.encode())]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/signals",
            "headers": headers,
        },
        receive,
    )


async def test_actual_stream_limit_does_not_trust_content_length() -> None:
    with pytest.raises(ValidationError, match="REQUEST_TOO_LARGE"):
        await read_limited_body(_request([b"1234", b"5678"], "1"), 6)


async def test_malformed_content_length_is_controlled() -> None:
    with pytest.raises(ValidationError, match="INVALID_CONTENT_LENGTH"):
        await read_limited_body(_request([b"{}"], "invalid"), 6)
