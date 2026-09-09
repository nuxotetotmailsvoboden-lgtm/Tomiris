from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Protocol

from tomiris_market_data.errors import ProviderError


class HostResolver(Protocol):
    async def validate(self, host: str, port: int, *, allow_non_global: bool = False) -> None: ...


class SecureHostResolver:
    """Resolve immediately before connect and reject any non-global production address."""

    async def validate(self, host: str, port: int, *, allow_non_global: bool = False) -> None:
        try:
            rows = await asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ProviderError("PROVIDER_DNS_ERROR", "provider DNS resolution failed") from exc
        addresses = {str(row[4][0]).split("%", maxsplit=1)[0] for row in rows}
        if not addresses:
            raise ProviderError("PROVIDER_DNS_ERROR", "provider resolved to no addresses")
        if not allow_non_global and any(
            not ipaddress.ip_address(value).is_global for value in addresses
        ):
            raise ProviderError(
                "PROVIDER_DNS_UNSAFE",
                "provider DNS resolution includes a private or special-use address",
            )


class StaticHostResolver:
    """Deterministic resolver for tests and controlled local harnesses."""

    def __init__(self, addresses: tuple[str, ...]) -> None:
        self.addresses = addresses

    async def validate(self, host: str, port: int, *, allow_non_global: bool = False) -> None:
        del host, port
        if not self.addresses:
            raise ProviderError("PROVIDER_DNS_ERROR", "provider resolved to no addresses")
        if not allow_non_global and any(
            not ipaddress.ip_address(value).is_global for value in self.addresses
        ):
            raise ProviderError("PROVIDER_DNS_UNSAFE", "unsafe deterministic DNS result")
