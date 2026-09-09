from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tomiris_market_data.capabilities import MarketDataType, ProviderCapabilities
from tomiris_market_data.errors import UnsupportedCapabilityError
from tomiris_market_data.identity import MarketType


class CapabilityAwareProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...


@dataclass(frozen=True)
class ProviderRoute:
    provider_id: str
    market_type: MarketType
    data_type: MarketDataType


class MarketDataProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, CapabilityAwareProvider] = {}

    def register(self, provider: CapabilityAwareProvider) -> None:
        provider_id = provider.capabilities.provider_id
        if provider_id in self._providers:
            raise ValueError(f"duplicate market-data provider: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> CapabilityAwareProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise UnsupportedCapabilityError(
                "PROVIDER_UNAVAILABLE", f"unknown provider {provider_id}"
            ) from exc

    def route(
        self,
        *,
        market_type: MarketType,
        data_type: MarketDataType,
        preferred_provider: str | None = None,
    ) -> CapabilityAwareProvider:
        candidates = (
            [self.get(preferred_provider)]
            if preferred_provider is not None
            else list(self._providers.values())
        )
        for provider in candidates:
            if provider.capabilities.supports(market_type, data_type):
                return provider
        raise UnsupportedCapabilityError(
            "UNSUPPORTED_CAPABILITY",
            f"no provider supports {market_type.value}/{data_type.value}",
        )

    def routes(self) -> tuple[ProviderRoute, ...]:
        return tuple(
            ProviderRoute(capabilities.provider_id, market_type, data_type)
            for provider in sorted(
                self._providers.values(), key=lambda item: item.capabilities.provider_id
            )
            for capabilities in (provider.capabilities,)
            for market_type in capabilities.market_types
            for data_type in capabilities.data_types
        )
