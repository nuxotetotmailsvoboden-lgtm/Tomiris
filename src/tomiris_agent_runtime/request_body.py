from __future__ import annotations

from fastapi import Request

from tomiris_hub.core.errors import ValidationError


async def read_limited_task_body(request: Request, maximum_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise ValidationError("INVALID_CONTENT_LENGTH", 400) from exc
        if declared < 0:
            raise ValidationError("INVALID_CONTENT_LENGTH", 400)
        if declared > maximum_bytes:
            raise ValidationError("TASK_REQUEST_TOO_LARGE", 413)
    collected = bytearray()
    async for chunk in request.stream():
        if len(collected) + len(chunk) > maximum_bytes:
            raise ValidationError("TASK_REQUEST_TOO_LARGE", 413)
        collected.extend(chunk)
    return bytes(collected)
