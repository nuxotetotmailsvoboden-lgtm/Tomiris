from __future__ import annotations

from datetime import datetime

from tomiris_agent_roles.models import AgentDefinition
from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.errors import UnsupportedCapabilityError
from tomiris_market_data.models import MarketDataRequest
from tomiris_market_data.registry import MarketDataProviderRegistry, ProviderRoute


class RoleDataPlanner:
    def plan(
        self, definition: AgentDefinition, *, asset: str, as_of: datetime
    ) -> tuple[MarketDataRequest, ...]:
        if asset not in definition.supported_assets:
            raise ValueError("task asset is not supported by the agent definition")
        relevant = [item for item in definition.required_data if item.instrument == asset]
        if not relevant:
            raise ValueError("agent definition has no data requirements for task asset")
        unsupported = [
            item.data_type for item in relevant if item.data_type != MarketDataType.OHLCV
        ]
        if unsupported:
            raise UnsupportedCapabilityError(
                "LEGACY_PLANNER_REQUIRES_OHLCV",
                "Phase 03 request adapter only produces OHLCV MarketDataRequest objects",
            )
        return tuple(
            MarketDataRequest(
                instrument=item.instrument,
                timeframe=item.timeframe,
                minimum_bars=item.minimum_bars,
                max_data_age_seconds=item.max_data_age_seconds,
                as_of=as_of,
                closed_only=True,
            )
            for item in relevant
        )

    def resolve_provider_routes(
        self,
        definition: AgentDefinition,
        *,
        asset: str,
        registry: MarketDataProviderRegistry,
    ) -> tuple[ProviderRoute, ...]:
        if asset not in definition.supported_assets:
            raise ValueError("task asset is not supported by the agent definition")
        relevant = [item for item in definition.required_data if item.instrument == asset]
        if not relevant:
            raise ValueError("agent definition has no data requirements for task asset")
        routes: list[ProviderRoute] = []
        for item in relevant:
            provider = registry.route(
                market_type=item.market_type,
                data_type=item.data_type,
                preferred_provider=item.preferred_provider,
            )
            routes.append(
                ProviderRoute(
                    provider_id=provider.capabilities.provider_id,
                    market_type=item.market_type,
                    data_type=item.data_type,
                )
            )
        return tuple(routes)
