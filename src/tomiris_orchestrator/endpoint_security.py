from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from tomiris_orchestrator.errors import EndpointSecurityError

AddressResolver = Callable[[str, int], Awaitable[list[str]]]


async def _system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(record[4][0]) for record in records})


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


class EndpointValidator:
    def __init__(
        self,
        allowed_host_suffixes: tuple[str, ...],
        *,
        resolver: AddressResolver = _system_resolver,
    ) -> None:
        self.allowed_host_suffixes = tuple(
            item.lstrip(".").lower() for item in allowed_host_suffixes
        )
        self.resolver = resolver

    async def validate(self, endpoint_url: str, environment: str) -> str:
        try:
            parsed = urlsplit(endpoint_url)
            port = parsed.port
        except ValueError as exc:
            raise EndpointSecurityError(
                "AGENT_ENDPOINT_FORBIDDEN", "malformed endpoint URL"
            ) from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise EndpointSecurityError("AGENT_ENDPOINT_FORBIDDEN", "HTTP(S) endpoint required")
        if parsed.username is not None or parsed.password is not None:
            raise EndpointSecurityError(
                "AGENT_ENDPOINT_FORBIDDEN", "credentials in URL are forbidden"
            )
        if parsed.query or parsed.fragment:
            raise EndpointSecurityError(
                "AGENT_ENDPOINT_FORBIDDEN", "query and fragment are forbidden"
            )
        if parsed.path not in {"", "/"}:
            raise EndpointSecurityError(
                "AGENT_ENDPOINT_FORBIDDEN", "endpoint must be an origin URL"
            )

        production = environment == "PRODUCTION"
        host = parsed.hostname.lower().rstrip(".")
        if production:
            if parsed.scheme != "https":
                raise EndpointSecurityError("AGENT_ENDPOINT_FORBIDDEN", "production requires HTTPS")
            if not any(
                host == suffix or host.endswith(f".{suffix}")
                for suffix in self.allowed_host_suffixes
            ):
                raise EndpointSecurityError(
                    "AGENT_ENDPOINT_FORBIDDEN", "host is outside the allowlist"
                )
            try:
                addresses = await self.resolver(host, port or 443)
            except OSError as exc:
                raise EndpointSecurityError(
                    "AGENT_UNAVAILABLE", "endpoint DNS resolution failed"
                ) from exc
            if not addresses or any(not _is_public(address) for address in addresses):
                raise EndpointSecurityError(
                    "AGENT_ENDPOINT_FORBIDDEN", "DNS resolved to a non-public address"
                )
        else:
            if host not in {"localhost", "127.0.0.1", "::1"} and parsed.scheme != "https":
                raise EndpointSecurityError(
                    "AGENT_ENDPOINT_FORBIDDEN", "development HTTP is localhost-only"
                )
        return endpoint_url.rstrip("/")
