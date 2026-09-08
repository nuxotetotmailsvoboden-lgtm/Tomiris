from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from tests.phase03_support import (
    StaticMarketDataProvider,
    load_pilot_definitions,
    make_series,
)
from tests.support import NOW

from tomiris_agent_roles.builtin import create_builtin_role_registry
from tomiris_agent_roles.planner import RoleDataPlanner
from tomiris_agent_runtime.analytical import AnalyticalRoleHandler, build_analytical_handler
from tomiris_agent_runtime.application import create_agent_runtime_app
from tomiris_agent_runtime.config import AgentRuntimeSettings
from tomiris_agent_runtime.sink import NullSignalSink
from tomiris_core_contracts.orchestration import AnalysisTaskRequest
from tomiris_core_contracts.signals import Bias
from tomiris_hub.core.clock import FakeClock
from tomiris_market_data.models import MarketDataRequest, MarketDataSeries
from tomiris_market_data.service import MarketDataCollector

COMMAND_SECRET = "phase03-command-0123456789abcdef0123456789"  # noqa: S105
INGEST_SECRET = "phase03-ingest-0123456789abcdef01234567890"  # noqa: S105


def settings(agent_id: str, definition_file: str, **changes: object) -> AgentRuntimeSettings:
    definition = load_pilot_definitions()[agent_id]
    values: dict[str, object] = {
        "_env_file": None,
        "tomiris_agent_id": agent_id,
        "tomiris_agent_role": definition.role_id,
        "tomiris_agent_capabilities": ",".join(definition.capabilities),
        "tomiris_agent_supported_assets": ",".join(definition.supported_assets),
        "tomiris_hub_url": "http://localhost:8000",
        "tomiris_hub_agent_secret": INGEST_SECRET,
        "tomiris_orchestrator_command_secret": COMMAND_SECRET,
        "tomiris_runtime_mode": "analytical",
        "tomiris_agent_definition_path": str(Path("agents/definitions") / definition_file),
    }
    values.update(changes)
    return AgentRuntimeSettings.model_validate(values)


def task(agent_id: str, *, context: dict[str, object] | None = None) -> AnalysisTaskRequest:
    definition = load_pilot_definitions()[agent_id]
    from uuid import uuid4

    return AnalysisTaskRequest(
        protocol_version="1.0",
        task_id=uuid4(),
        orchestration_run_id=uuid4(),
        snapshot_id=uuid4(),
        agent_id=agent_id,
        asset=definition.supported_assets[0],
        required_capability=definition.capabilities[0],
        priority=50,
        created_at=NOW,
        deadline=NOW + timedelta(minutes=5),
        correlation_id=uuid4(),
        context=context or {},
    )


def handler(agent_id: str, provider: StaticMarketDataProvider) -> AnalyticalRoleHandler:
    definition = load_pilot_definitions()[agent_id]
    role = create_builtin_role_registry().build(definition)
    return AnalyticalRoleHandler(
        role,
        MarketDataCollector(provider),
        RoleDataPlanner(),
        FakeClock(NOW),
    )


@pytest.mark.parametrize(
    ("agent_id", "file_name"),
    [
        ("BTC_CONTEXT_001", "btc_context_001.yaml"),
        ("ETH_TECHNICAL_001", "eth_technical_001.yaml"),
        ("SOL_TECHNICAL_001", "sol_technical_001.yaml"),
    ],
)
def test_one_runtime_factory_loads_each_role(agent_id: str, file_name: str) -> None:
    configured = build_analytical_handler(
        settings(agent_id, file_name),
        FakeClock(NOW),
    )
    assert configured.role.definition.agent_id == agent_id
    assert isinstance(NullSignalSink(), NullSignalSink)


async def test_universal_runtime_selects_analytical_mode_without_external_http() -> None:
    configured = settings("ETH_TECHNICAL_001", "eth_technical_001.yaml")
    app = create_agent_runtime_app(
        configured,
        sink=NullSignalSink(),
        clock=FakeClock(NOW),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://runtime.test",
    ) as client:
        ready = await client.get("/health/ready")
        capabilities = await client.get("/v1/capabilities")
    assert ready.json()["role_api_version"] == "1"
    assert capabilities.json()["role"] == "eth.technical.v1"
    assert capabilities.json()["analytical_role_api_version"] == "1"


def test_analytical_runtime_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError, match="DEFINITION_PATH"):
        AgentRuntimeSettings(
            _env_file=None,
            tomiris_agent_id="ETH_TECHNICAL_001",
            tomiris_agent_role="eth.technical.v1",
            tomiris_agent_capabilities="technical.multi_timeframe",
            tomiris_agent_supported_assets="ETHUSDT",
            tomiris_hub_url="http://localhost:8000",
            tomiris_hub_agent_secret=INGEST_SECRET,
            tomiris_orchestrator_command_secret=COMMAND_SECRET,
            tomiris_runtime_mode="analytical",
        )
    wrong_role = settings(
        "ETH_TECHNICAL_001",
        "eth_technical_001.yaml",
        tomiris_agent_role="sol.technical.v1",
    )
    with pytest.raises(ValueError, match="ROLE"):
        build_analytical_handler(wrong_role, FakeClock(NOW))


async def test_handler_produces_versioned_signal_with_bounded_evidence() -> None:
    selected = handler("ETH_TECHNICAL_001", StaticMarketDataProvider())
    signal = await selected.analyze(task("ETH_TECHNICAL_001"))
    assert signal.bias == Bias.LONG
    assert signal.role_id == "eth.technical.v1"
    assert signal.role_version == "1.0.0"
    assert signal.config_version == "eth-technical-config.v1"
    assert signal.feature_pipeline_version == "technical-pipeline.v1"
    assert signal.analysis_schema_version == "1"
    assert signal.confidence_model_version == "deterministic-agreement.v1"
    assert len(signal.evidence) <= 20
    assert all(item.feature_version for item in signal.evidence)
    assert len(signal.metadata["data_ranges"]) == 4
    assert signal.metadata["analysis_as_of"] == NOW.isoformat()
    assert signal.metadata["agent_signal_is_trade_decision"] is False
    assert selected.metrics.counters[("agent_analysis_total", "eth.technical.v1", "ETHUSDT")] == 1
    assert (
        len(
            selected.metrics.observations[("agent_analysis_latency", "eth.technical.v1", "ETHUSDT")]
        )
        == 1
    )


@pytest.mark.parametrize(
    "failure_code",
    ["PROVIDER_ERROR", "PROVIDER_TIMEOUT", "INSUFFICIENT_HISTORY", "DATA_STALE"],
)
async def test_provider_and_quality_failures_are_abstain_not_neutral(
    failure_code: str,
) -> None:
    selected = handler(
        "SOL_TECHNICAL_001",
        StaticMarketDataProvider(failure_code=failure_code),
    )
    signal = await selected.analyze(task("SOL_TECHNICAL_001"))
    assert signal.bias == Bias.ABSTAIN
    assert signal.confidence == 0
    assert signal.risk_flags == [failure_code]
    assert (
        selected.metrics.counters[("agent_analysis_failure_total", "sol.technical.v1", "SOLUSDT")]
        == 1
    )
    assert (
        selected.metrics.counters[("agent_analysis_abstain_total", "sol.technical.v1", "SOLUSDT")]
        == 1
    )


class InvalidQualityProvider(StaticMarketDataProvider):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode

    async def get_ohlcv(self, request: MarketDataRequest) -> MarketDataSeries:
        count = request.minimum_bars - 1 if self.mode == "short" else request.minimum_bars
        as_of = (
            request.as_of - timedelta(seconds=request.max_data_age_seconds + 1)
            if self.mode == "stale"
            else request.as_of
        )
        series = make_series(
            instrument=request.instrument,
            timeframe=request.timeframe,
            as_of=as_of,
            count=count,
        )
        return series.model_copy(update={"as_of": request.as_of})


@pytest.mark.parametrize(
    ("mode", "reason"),
    [("short", "INSUFFICIENT_HISTORY"), ("stale", "DATA_STALE")],
)
async def test_real_quality_gate_failure_becomes_abstain(mode: str, reason: str) -> None:
    selected = handler("ETH_TECHNICAL_001", InvalidQualityProvider(mode))
    signal = await selected.analyze(task("ETH_TECHNICAL_001"))
    assert signal.bias == Bias.ABSTAIN
    assert signal.risk_flags == [reason]


async def test_analysis_cutoff_rejects_future_and_is_replayable() -> None:
    selected = handler("BTC_CONTEXT_001", StaticMarketDataProvider())
    selected_task = task("BTC_CONTEXT_001")
    first = await selected.analyze(selected_task)
    second = await selected.analyze(selected_task)
    first_content = first.model_dump(exclude={"message_id", "agent_run_id"})
    second_content = second.model_dump(exclude={"message_id", "agent_run_id"})
    assert first_content == second_content
    historical = task(
        "BTC_CONTEXT_001",
        context={"analysis_as_of": (NOW - timedelta(days=365)).isoformat()},
    )
    historical_signal = await selected.analyze(historical)
    assert historical_signal.metadata["analysis_as_of"] == (NOW - timedelta(days=365)).isoformat()
    with pytest.raises(ValueError, match="future"):
        await selected.analyze(
            task(
                "BTC_CONTEXT_001",
                context={"analysis_as_of": (NOW + timedelta(seconds=1)).isoformat()},
            )
        )


async def test_handler_rejects_wrong_agent_identity_and_records_latency() -> None:
    selected = handler("ETH_TECHNICAL_001", StaticMarketDataProvider())
    wrong_task = task("SOL_TECHNICAL_001")
    with pytest.raises(ValueError, match="agent"):
        await selected.analyze(wrong_task)
    assert (
        len(
            selected.metrics.observations[("agent_analysis_latency", "eth.technical.v1", "SOLUSDT")]
        )
        == 1
    )
