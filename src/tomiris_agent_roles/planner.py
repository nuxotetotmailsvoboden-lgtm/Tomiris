from __future__ import annotations

from datetime import datetime

from tomiris_agent_roles.models import AgentDefinition
from tomiris_market_data.models import MarketDataRequest


class RoleDataPlanner:
    def plan(
        self, definition: AgentDefinition, *, asset: str, as_of: datetime
    ) -> tuple[MarketDataRequest, ...]:
        if asset not in definition.supported_assets:
            raise ValueError("task asset is not supported by the agent definition")
        relevant = [item for item in definition.required_data if item.instrument == asset]
        if not relevant:
            raise ValueError("agent definition has no data requirements for task asset")
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
