from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.phase03_support import load_pilot_definitions, make_bundle
from tests.support import NOW

from tomiris_agent_roles.builtin import create_builtin_role_registry
from tomiris_agent_roles.definitions import AgentDefinitionLoader
from tomiris_agent_roles.models import (
    AgentAnalysisResult,
    AgentDefinition,
    AnalysisContext,
    RoleInput,
)
from tomiris_agent_roles.registry import AgentRoleRegistry
from tomiris_core_contracts.orchestration import AnalysisTaskRequest
from tomiris_core_contracts.signals import Bias
from tomiris_market_data.models import DataQualityOutcome, Timeframe


def task(agent_id: str, asset: str, capability: str) -> AnalysisTaskRequest:
    return AnalysisTaskRequest(
        protocol_version="1.0",
        task_id=uuid4(),
        orchestration_run_id=uuid4(),
        snapshot_id=uuid4(),
        agent_id=agent_id,
        asset=asset,
        required_capability=capability,
        priority=50,
        created_at=NOW,
        deadline=NOW + timedelta(minutes=5),
        correlation_id=uuid4(),
    )


def analyze_pilot(
    agent_id: str,
    pattern_by_timeframe: dict[Timeframe, str],
) -> AgentAnalysisResult:
    definitions = load_pilot_definitions()
    definition = definitions[agent_id]
    role = create_builtin_role_registry().build(definition)
    selected_task = task(agent_id, definition.supported_assets[0], definition.capabilities[0])
    context = AnalysisContext(
        task=selected_task,
        snapshot_id=selected_task.snapshot_id,
        as_of=NOW,
    )
    bundle = make_bundle(
        selected_task.snapshot_id,
        instrument=selected_task.asset,
        as_of=NOW,
        pattern_by_timeframe=pattern_by_timeframe,
    )
    return role.analyze(RoleInput(context=context, market_data=bundle))


def test_registry_loads_all_pilot_roles_without_runtime_or_http() -> None:
    registry = create_builtin_role_registry()
    definitions = AgentDefinitionLoader(registry).load_directory(Path("agents/definitions"))
    assert registry.role_ids() == (
        "btc.market_context.v1",
        "eth.technical.v1",
        "sol.technical.v1",
    )
    assert set(definitions) == {"BTC_CONTEXT_001", "ETH_TECHNICAL_001", "SOL_TECHNICAL_001"}
    assert all(registry.build(item).definition == item for item in definitions.values())


def test_unknown_duplicate_and_incompatible_roles_fail_closed() -> None:
    definitions = load_pilot_definitions()
    registry = create_builtin_role_registry()
    unknown = definitions["ETH_TECHNICAL_001"].model_copy(update={"role_id": "unknown.role.v1"})
    with pytest.raises(ValueError, match="unknown"):
        registry.build(unknown)
    from tomiris_agent_roles.eth_technical import ETHTechnicalRolePlugin

    with pytest.raises(ValueError, match="duplicate"):
        registry.register(ETHTechnicalRolePlugin())
    mismatched = definitions["ETH_TECHNICAL_001"].model_copy(
        update={"supported_assets": ("SOLUSDT",)}
    )
    with pytest.raises(ValueError, match="ETH"):
        registry.build(mismatched)


def test_invalid_definition_and_config_are_rejected() -> None:
    base = load_pilot_definitions()["ETH_TECHNICAL_001"].model_dump(mode="json")
    base["required_data"][0]["timeframe"] = "2h"
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate(base)
    definition = load_pilot_definitions()["ETH_TECHNICAL_001"]
    bad_config = definition.model_copy(
        update={"parameters": {"pipeline": {"ema_fast": 50, "ema_slow": 20}}}
    )
    with pytest.raises(ValidationError):
        create_builtin_role_registry().build(bad_config)


@pytest.mark.parametrize(
    ("agent_id", "pattern", "expected"),
    [
        ("BTC_CONTEXT_001", "up", Bias.LONG),
        ("BTC_CONTEXT_001", "down", Bias.SHORT),
        ("ETH_TECHNICAL_001", "up", Bias.LONG),
        ("ETH_TECHNICAL_001", "down", Bias.SHORT),
        ("SOL_TECHNICAL_001", "up", Bias.LONG),
        ("SOL_TECHNICAL_001", "down", Bias.SHORT),
    ],
)
def test_pilot_golden_directional_outcomes(agent_id: str, pattern: str, expected: Bias) -> None:
    result = analyze_pilot(agent_id, {timeframe: pattern for timeframe in Timeframe})
    assert result.bias == expected
    assert result.data_quality == DataQualityOutcome.VALID
    assert 0 <= result.confidence <= 1
    assert result.evidence


def test_range_and_conflicting_timeframes_are_neutral_not_abstain() -> None:
    ranged = analyze_pilot("ETH_TECHNICAL_001", {timeframe: "range" for timeframe in Timeframe})
    btc_context = analyze_pilot("BTC_CONTEXT_001", {timeframe: "range" for timeframe in Timeframe})
    conflict = analyze_pilot(
        "ETH_TECHNICAL_001",
        {
            Timeframe.D1: "up",
            Timeframe.H4: "down",
            Timeframe.H1: "up",
            Timeframe.M15: "down",
        },
    )
    assert ranged.bias == Bias.NEUTRAL
    assert btc_context.bias == Bias.NEUTRAL
    assert conflict.bias == Bias.NEUTRAL
    assert "TIMEFRAME_CONFLICT" in conflict.reason_codes
    assert ranged.data_quality == DataQualityOutcome.VALID


def test_sol_high_volatility_is_explicit_and_not_silently_directional() -> None:
    result = analyze_pilot(
        "SOL_TECHNICAL_001",
        {timeframe: "high_volatility" for timeframe in Timeframe},
    )
    assert "HIGH_VOLATILITY" in result.reason_codes
    assert all(state.volatility.value in {"HIGH", "EXTREME"} for state in result.timeframe_states)


def test_wrong_asset_bundle_abstains_and_repeated_analysis_is_deterministic() -> None:
    definitions = load_pilot_definitions()
    definition = definitions["ETH_TECHNICAL_001"]
    role = create_builtin_role_registry().build(definition)
    selected_task = task("ETH_TECHNICAL_001", "ETHUSDT", "technical.multi_timeframe")
    context = AnalysisContext(task=selected_task, snapshot_id=selected_task.snapshot_id, as_of=NOW)
    correct_input = RoleInput(
        context=context,
        market_data=make_bundle(selected_task.snapshot_id, instrument="ETHUSDT", as_of=NOW),
    )
    first = role.analyze(correct_input)
    assert first == role.analyze(correct_input)
    wrong_input = RoleInput(
        context=context,
        market_data=make_bundle(selected_task.snapshot_id, instrument="SOLUSDT", as_of=NOW),
    )
    wrong = role.analyze(wrong_input)
    assert wrong.bias == Bias.ABSTAIN
    assert wrong.reason_codes == ("FEATURE_FAILURE",)


def test_wrong_snapshot_and_missing_timeframe_fail_closed() -> None:
    definition = load_pilot_definitions()["ETH_TECHNICAL_001"]
    role = create_builtin_role_registry().build(definition)
    selected_task = task("ETH_TECHNICAL_001", "ETHUSDT", "technical.multi_timeframe")
    context = AnalysisContext(task=selected_task, snapshot_id=selected_task.snapshot_id, as_of=NOW)
    with pytest.raises(ValidationError, match="snapshot"):
        RoleInput(
            context=context,
            market_data=make_bundle(uuid4(), instrument="ETHUSDT", as_of=NOW),
        )
    incomplete = make_bundle(
        selected_task.snapshot_id,
        instrument="ETHUSDT",
        as_of=NOW,
        pattern_by_timeframe={Timeframe.H1: "up"},
    )
    result = role.analyze(RoleInput(context=context, market_data=incomplete))
    assert result.bias == Bias.ABSTAIN
    assert result.reason_codes == ("INSUFFICIENT_HISTORY",)


class DummyRole:
    role_id = "dummy.new.v1"
    role_version = "1.0.0"
    feature_pipeline_version = "dummy-pipeline.v1"
    analysis_schema_version = "1"

    def __init__(self, definition: AgentDefinition) -> None:
        self.definition = definition

    def analyze(self, role_input: RoleInput) -> AgentAnalysisResult:
        return AgentAnalysisResult(
            analysis_schema_version="1",
            role_id=self.role_id,
            role_version=self.role_version,
            config_version=self.definition.config_version,
            feature_pipeline_version=self.feature_pipeline_version,
            snapshot_id=role_input.context.snapshot_id,
            asset=role_input.context.task.asset,
            bias=Bias.NEUTRAL,
            confidence=0.5,
            data_quality=DataQualityOutcome.VALID,
            reason_codes=("NO_CLEAR_EDGE",),
            data_provider="fixture",
            data_as_of=role_input.context.as_of,
            analysis_as_of=role_input.context.as_of,
        )


class DummyPlugin:
    role_id = "dummy.new.v1"
    role_version = "1.0.0"
    role_api_version = "1"

    def build(self, definition: AgentDefinition) -> DummyRole:
        return DummyRole(definition)


def dummy_definition(index: int) -> AgentDefinition:
    return AgentDefinition(
        agent_id=f"DUMMY_AGENT_{index:03d}",
        role_id="dummy.new.v1",
        config_version="dummy-config.v1",
        supported_assets=("TEST",),
        capabilities=("dummy.capability",),
        required_data=(
            {
                "instrument": "TEST",
                "timeframe": "1h",
                "minimum_bars": 10,
                "max_data_age_seconds": 7_200,
            },
        ),
    )


def test_dummy_plugin_and_100_agent_definitions_need_no_core_changes() -> None:
    registry = AgentRoleRegistry()
    registry.register(DummyPlugin())
    roles = [registry.build(dummy_definition(index)) for index in range(100)]
    assert len(roles) == 100
    assert {role.definition.agent_id for role in roles} == {
        f"DUMMY_AGENT_{index:03d}" for index in range(100)
    }
    assert all(role.role_id == "dummy.new.v1" for role in roles)
