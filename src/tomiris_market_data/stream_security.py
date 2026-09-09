from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

_STREAM_NAME = re.compile(r"^[a-z0-9_!@.-]{1,128}$")


class BinanceStreamEndpointPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str = "wss://fstream.binance.com/stream"
    allowed_host_suffixes: tuple[str, ...] = ("binance.com",)
    allow_insecure_localhost: bool = False
    max_streams: int = Field(default=100, ge=1, le=1_000)

    @model_validator(mode="after")
    def validate_endpoint(self) -> BinanceStreamEndpointPolicy:
        try:
            parsed = urlsplit(self.base_url)
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("malformed websocket URL") from exc
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("websocket endpoint must be a credential-free URL")
        if parsed.query or parsed.fragment or parsed.path not in {"/stream", "/ws"}:
            raise ValueError("websocket endpoint path is not approved")
        host = parsed.hostname.lower().rstrip(".")
        local = host in {"localhost", "127.0.0.1", "::1"}
        if local and not self.allow_insecure_localhost:
            raise ValueError("localhost websocket requires explicit dev override")
        if parsed.scheme != "wss" and not (local and self.allow_insecure_localhost):
            raise ValueError("production websocket requires WSS")
        allowed = any(
            host == suffix.lstrip(".").lower() or host.endswith(f".{suffix.lstrip('.').lower()}")
            for suffix in self.allowed_host_suffixes
        )
        if not local and not allowed:
            raise ValueError("websocket host is outside the allowlist")
        return self

    def combined_url(self, stream_names: tuple[str, ...]) -> str:
        if not stream_names or len(stream_names) > self.max_streams:
            raise ValueError("stream subscription count is outside bounds")
        normalized = tuple(name.lower() for name in stream_names)
        if len(set(normalized)) != len(normalized):
            raise ValueError("stream subscriptions must be unique")
        if any(_STREAM_NAME.fullmatch(name) is None for name in normalized):
            raise ValueError("invalid stream subscription name")
        parsed = urlsplit(self.base_url)
        query = f"streams={'/'.join(quote(name, safe='@_!.-') for name in normalized)}"
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))
