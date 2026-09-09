from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from tests.phase03_support import load_pilot_definitions
from tests.phase04_support import ETH_FUTURES, ETH_SPOT, NOW, mark_event

from tomiris_agent_roles.planner import RoleDataPlanner
from tomiris_market_data.binance import BinancePublicMarketDataProvider
from tomiris_market_data.capabilities import MarketDataType, ProviderCapabilities
from tomiris_market_data.errors import UnsupportedCapabilityError
from tomiris_market_data.identity import CanonicalInstrument, ContractType, MarketType
from tomiris_market_data.models import DataQualityOutcome
from tomiris_market_data.quality import MarketDataQualityEngine, MarketDataQualityPolicy
from tomiris_market_data.registry import MarketDataProviderRegistry
from tomiris_market_data.time import (
    ClockDriftMonitor,
    ClockDriftPolicy,
    TimeSyncState,
)


def test_canonical_identity_prevents_spot_futures_collision() -> None:
    assert ETH_SPOT.instrument_id == "BINANCE:SPOT:ETHUSDT"
    assert ETH_FUTURES.instrument_id == "BINANCE:USDT_M_FUTURES:ETHUSDT"
    assert ETH_SPOT != ETH_FUTURES
    with pytest.raises(ValidationError):
        CanonicalInstrument(
            venue="BINANCE",
            market_type=MarketType.SPOT,
            symbol="ETHUSDT",
            base_asset="ETH",
            quote_asset="USDT",
            contract_type=ContractType.PERPETUAL,
        )


@pytest.mark.parametrize(
    ("offset_ms", "expected"),
    [(100, TimeSyncState.HEALTHY), (700, TimeSyncState.DEGRADED), (2_500, TimeSyncState.UNSAFE)],
)
def test_clock_drift_states_are_deterministic(offset_ms: int, expected: TimeSyncState) -> None:
    measurement = ClockDriftMonitor(
        ClockDriftPolicy(degraded_threshold_ms=500, unsafe_threshold_ms=2_000)
    ).measure(
        provider="fixture-provider",
        exchange_time=NOW + timedelta(milliseconds=offset_ms),
        request_started_at=NOW - timedelta(milliseconds=10),
        response_received_at=NOW + timedelta(milliseconds=10),
    )
    assert measurement.state == expected
    assert measurement.safe_for_snapshot is (expected != TimeSyncState.UNSAFE)


def test_quality_dimensions_veto_stale_and_unsafe_data() -> None:
    event = mark_event(event_time=NOW - timedelta(seconds=11))
    report = MarketDataQualityEngine().evaluate_event(
        event,
        observed_at=NOW,
        policy=MarketDataQualityPolicy(max_age_seconds=10),
    )
    assert report.overall_state == DataQualityOutcome.INVALID
    assert report.safe_for_analysis is False
    assert "DATA_STALE" in report.reason_codes
    assert len(report.dimensions) == 9


def test_registry_routes_declarative_capabilities_and_scales_to_100() -> None:
    class Provider:
        def __init__(self, index: int) -> None:
            self._capabilities = ProviderCapabilities(
                provider_id=f"fixture-{index:03d}",
                venue="FIXTURE",
                market_types=(MarketType.SPOT,),
                data_types=(MarketDataType.OHLCV,),
            )

        @property
        def capabilities(self) -> ProviderCapabilities:
            return self._capabilities

    registry = MarketDataProviderRegistry()
    for index in range(100):
        registry.register(Provider(index))
    assert len(registry.routes()) == 100
    routed = registry.route(
        market_type=MarketType.SPOT,
        data_type=MarketDataType.OHLCV,
        preferred_provider="fixture-042",
    )
    assert routed.capabilities.provider_id == "fixture-042"
    with pytest.raises(UnsupportedCapabilityError) as caught:
        registry.route(
            market_type=MarketType.USDT_M_FUTURES,
            data_type=MarketDataType.FUNDING_RATE,
        )
    assert caught.value.code == "UNSUPPORTED_CAPABILITY"


def test_phase03_role_planner_remains_compatible_with_default_ohlcv() -> None:
    definition = load_pilot_definitions()["ETH_TECHNICAL_001"]
    planner = RoleDataPlanner()
    planned = planner.plan(definition, asset="ETHUSDT", as_of=NOW)
    assert len(planned) == 4
    registry = MarketDataProviderRegistry()
    registry.register(BinancePublicMarketDataProvider())
    routes = planner.resolve_provider_routes(definition, asset="ETHUSDT", registry=registry)
    assert len(routes) == 4
    assert {route.provider_id for route in routes} == {"binance-public"}


def test_legacy_request_adapter_rejects_new_capability_as_controlled_error() -> None:
    definition = load_pilot_definitions()["ETH_TECHNICAL_001"]
    derivative_requirement = definition.required_data[0].model_copy(
        update={
            "data_type": MarketDataType.FUNDING_RATE,
            "market_type": MarketType.USDT_M_FUTURES,
        }
    )
    extended = definition.model_copy(update={"required_data": (derivative_requirement,)})
    with pytest.raises(UnsupportedCapabilityError) as caught:
        RoleDataPlanner().plan(extended, asset="ETHUSDT", as_of=NOW)
    assert caught.value.code == "LEGACY_PLANNER_REQUIRES_OHLCV"
