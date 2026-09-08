from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from tomiris_agent_roles.builtin import create_builtin_role_registry
from tomiris_agent_roles.definitions import AgentDefinitionLoader
from tomiris_agent_roles.planner import RoleDataPlanner
from tomiris_agent_runtime.analytical import AnalyticalRoleHandler
from tomiris_core_contracts.orchestration import AnalysisTaskRequest
from tomiris_hub.core.clock import SystemClock
from tomiris_market_data.binance import (
    BinanceProviderSettings,
    BinancePublicMarketDataProvider,
)
from tomiris_market_data.cache import InMemoryMarketDataCache
from tomiris_market_data.service import MarketDataCollector


async def run(definition_directory: Path, base_url: str) -> dict[str, object]:
    clock = SystemClock()
    as_of = clock.now()
    snapshot_id = uuid4()
    registry = create_builtin_role_registry()
    definitions = AgentDefinitionLoader(registry).load_directory(definition_directory)
    provider = BinancePublicMarketDataProvider(
        BinanceProviderSettings(base_url=base_url),
        cache=InMemoryMarketDataCache(),
    )

    async def analyze(agent_id: str) -> dict[str, object]:
        definition = definitions[agent_id]
        role = registry.build(definition)
        task = AnalysisTaskRequest(
            protocol_version="1.0",
            task_id=uuid4(),
            orchestration_run_id=uuid4(),
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            asset=definition.supported_assets[0],
            required_capability=definition.capabilities[0],
            priority=50,
            created_at=as_of,
            deadline=as_of + timedelta(minutes=10),
            correlation_id=uuid4(),
            context={"analysis_as_of": as_of.isoformat()},
        )
        handler = AnalyticalRoleHandler(
            role,
            MarketDataCollector(provider),
            RoleDataPlanner(),
            clock,
        )
        signal = await handler.analyze(task)
        return {
            "agent_id": agent_id,
            "status": "COMPLETED",
            "analytical_bias": signal.bias.value,
            "confidence_strength": signal.confidence / 100,
            "data_as_of": signal.data_as_of.isoformat() if signal.data_as_of else None,
            "role_id": signal.role_id,
            "role_version": signal.role_version,
            "config_version": signal.config_version,
            "reason_codes": signal.risk_flags,
            "agent_signal_is_trade_decision": False,
        }

    results = await asyncio.gather(*(analyze(agent_id) for agent_id in sorted(definitions)))
    return {
        "snapshot_id": str(snapshot_id),
        "analysis_as_of": as_of.isoformat(),
        "agents": results,
        "pilot_cycle": "FULL" if len(results) == len(definitions) else "INCOMPLETE",
        "trade_execution": "DISABLED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the three TOMIRIS pilot analytical roles on public market data."
    )
    parser.add_argument(
        "--definitions",
        type=Path,
        default=Path("agents/definitions"),
        help="Directory containing validated agent definitions.",
    )
    parser.add_argument(
        "--provider-base-url",
        default="https://api.binance.com",
        help="HTTPS Binance public API origin.",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.definitions, args.provider_base_url)), indent=2))


if __name__ == "__main__":
    main()
