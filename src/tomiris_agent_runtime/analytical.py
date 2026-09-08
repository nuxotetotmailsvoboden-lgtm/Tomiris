from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from tomiris_agent_roles.base import AnalyticalRole
from tomiris_agent_roles.builtin import create_builtin_role_registry
from tomiris_agent_roles.definitions import AgentDefinitionLoader
from tomiris_agent_roles.metrics import AnalysisMetrics
from tomiris_agent_roles.models import (
    AgentAnalysisResult,
    AnalysisContext,
    RoleInput,
)
from tomiris_agent_roles.planner import RoleDataPlanner
from tomiris_agent_runtime.config import AgentRuntimeSettings
from tomiris_core_contracts.orchestration import AnalysisTaskRequest
from tomiris_core_contracts.signals import Bias, EvidenceItem, SignalEnvelope
from tomiris_hub.core.clock import Clock
from tomiris_market_data.binance import (
    BinanceProviderSettings,
    BinancePublicMarketDataProvider,
)
from tomiris_market_data.errors import MarketDataError
from tomiris_market_data.models import DataQualityOutcome, require_utc
from tomiris_market_data.service import MarketDataCollector

logger = logging.getLogger(__name__)


class AnalyticalRoleHandler:
    """Bridges transport/runtime concerns to a transport-independent role plugin."""

    confidence_model_version = "deterministic-agreement.v1"

    def __init__(
        self,
        role: AnalyticalRole,
        collector: MarketDataCollector,
        planner: RoleDataPlanner,
        clock: Clock,
        metrics: AnalysisMetrics | None = None,
    ) -> None:
        self.role = role
        self.collector = collector
        self.planner = planner
        self.clock = clock
        self.metrics = metrics or AnalysisMetrics()

    async def analyze(self, task: AnalysisTaskRequest) -> SignalEnvelope:
        started = time.perf_counter()
        self.metrics.increment("agent_analysis_total", self.role.role_id, task.asset)
        try:
            if task.agent_id != self.role.definition.agent_id:
                raise ValueError("task agent does not match analytical role definition")
            as_of = self._analysis_cutoff(task)
            context = AnalysisContext(task=task, snapshot_id=task.snapshot_id, as_of=as_of)
            try:
                requests = self.planner.plan(self.role.definition, asset=task.asset, as_of=as_of)
                collected = await self.collector.collect(task.snapshot_id, as_of, requests)
                result = self.role.analyze(RoleInput(context=context, market_data=collected.bundle))
            except MarketDataError as exc:
                self.metrics.increment(
                    "agent_analysis_failure_total", self.role.role_id, task.asset
                )
                logger.warning(
                    "analytical_market_data_rejected",
                    extra={
                        "agent_id": task.agent_id,
                        "role_id": self.role.role_id,
                        "asset": task.asset,
                        "snapshot_id": str(task.snapshot_id),
                        "task_id": str(task.task_id),
                        "provider": self.collector.provider.name,
                        "outcome": "ABSTAIN",
                        "reason_code": exc.code,
                    },
                )
                result = self._provider_abstention(task, as_of, exc.code)
            if result.bias == Bias.ABSTAIN:
                self.metrics.increment(
                    "agent_analysis_abstain_total", self.role.role_id, task.asset
                )
                if "FEATURE_FAILURE" in result.reason_codes:
                    self.metrics.increment(
                        "agent_analysis_failure_total", self.role.role_id, task.asset
                    )
            latency_ms = (time.perf_counter() - started) * 1_000
            logger.info(
                "agent_analysis_completed",
                extra={
                    "agent_id": task.agent_id,
                    "role_id": result.role_id,
                    "role_version": result.role_version,
                    "asset": task.asset,
                    "snapshot_id": str(task.snapshot_id),
                    "task_id": str(task.task_id),
                    "provider": result.data_provider,
                    "data_as_of": result.data_as_of.isoformat(),
                    "outcome": result.bias.value,
                    "reason_code": result.reason_codes[0] if result.reason_codes else None,
                    "latency_ms": round(latency_ms, 3),
                },
            )
            return self._to_signal(task, result)
        finally:
            self.metrics.observe_latency(
                self.role.role_id,
                task.asset,
                (time.perf_counter() - started) * 1_000,
            )

    def _analysis_cutoff(self, task: AnalysisTaskRequest) -> datetime:
        raw = task.context.get("analysis_as_of")
        if raw is None:
            return task.created_at
        if not isinstance(raw, str):
            raise ValueError("analysis_as_of must be an ISO-8601 string")
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        require_utc(value)
        if value > self.clock.now():
            raise ValueError("analysis_as_of cannot be in the future")
        return value

    def _provider_abstention(
        self, task: AnalysisTaskRequest, as_of: datetime, reason: str
    ) -> AgentAnalysisResult:
        quality = (
            DataQualityOutcome.INSUFFICIENT
            if reason == "INSUFFICIENT_HISTORY"
            else DataQualityOutcome.INVALID
        )
        return AgentAnalysisResult(
            analysis_schema_version=self.role.analysis_schema_version,
            role_id=self.role.role_id,
            role_version=self.role.role_version,
            config_version=self.role.definition.config_version,
            feature_pipeline_version=self.role.feature_pipeline_version,
            snapshot_id=task.snapshot_id,
            asset=task.asset,
            bias=Bias.ABSTAIN,
            confidence=0,
            data_quality=quality,
            reason_codes=(reason,),
            data_provider=self.collector.provider.name,
            data_as_of=as_of,
            analysis_as_of=as_of,
        )

    def _to_signal(self, task: AnalysisTaskRequest, result: AgentAnalysisResult) -> SignalEnvelope:
        now = self.clock.now()
        evidence = [
            EvidenceItem(
                evidence_type=item.evidence_type,
                summary=item.summary,
                source_type="public_market_data",
                source_id=f"{item.provider}:{item.instrument}:{item.timeframe.value}",
                provider=item.provider,
                observed_at=item.observed_at,
                source_timestamp=item.source_timestamp,
                instrument=item.instrument,
                timeframe=item.timeframe.value,
                feature_name=item.feature_name,
                feature_version=item.feature_version,
                observation=item.observation,
            )
            for item in result.evidence
        ]
        max_strength = max((abs(item.score) for item in result.timeframe_states), default=0.0)
        return SignalEnvelope(
            protocol_version="1.0",
            message_id=uuid4(),
            agent_id=task.agent_id,
            agent_run_id=uuid4(),
            snapshot_id=task.snapshot_id,
            task_id=task.task_id,
            orchestration_run_id=task.orchestration_run_id,
            correlation_id=task.correlation_id,
            causation_id=task.task_id,
            asset=task.asset,
            bias=result.bias,
            confidence=round(result.confidence * 100),
            impact=round(max_strength * 100),
            time_horizon="multi-timeframe-context",
            evidence=evidence,
            risk_flags=list(result.reason_codes),
            data_timestamp=result.data_as_of,
            analysis_timestamp=now,
            signal_ttl_seconds=min(300, max(1, int((task.deadline - now).total_seconds()))),
            role_id=result.role_id,
            role_version=result.role_version,
            config_version=result.config_version,
            feature_pipeline_version=result.feature_pipeline_version,
            analysis_schema_version=result.analysis_schema_version,
            data_provider=result.data_provider,
            data_as_of=result.data_as_of,
            confidence_model_version=self.confidence_model_version,
            metadata={
                "data_quality": result.data_quality.value,
                "reason_codes": list(result.reason_codes),
                "timeframe_states": [
                    item.model_dump(mode="json") for item in result.timeframe_states
                ],
                "data_ranges": [item.model_dump(mode="json") for item in result.data_ranges],
                "analysis_as_of": result.analysis_as_of.isoformat(),
                "agent_signal_is_trade_decision": False,
            },
        )


def build_analytical_handler(
    settings: AgentRuntimeSettings,
    clock: Clock,
) -> AnalyticalRoleHandler:
    if settings.tomiris_agent_definition_path is None:
        raise ValueError("TOMIRIS_AGENT_DEFINITION_PATH is required for analytical roles")
    registry = create_builtin_role_registry()
    definition = AgentDefinitionLoader(registry).load_file(
        Path(settings.tomiris_agent_definition_path)
    )
    if definition.agent_id != settings.tomiris_agent_id:
        raise ValueError("runtime AGENT_ID does not match agent definition")
    if definition.role_id != settings.tomiris_agent_role:
        raise ValueError("runtime ROLE does not match agent definition")
    if set(definition.capabilities) != set(settings.capabilities):
        raise ValueError("runtime capabilities do not match agent definition")
    if set(definition.supported_assets) != set(settings.supported_assets):
        raise ValueError("runtime assets do not match agent definition")
    role = registry.build(definition)
    provider = BinancePublicMarketDataProvider(
        BinanceProviderSettings(
            base_url=settings.market_data_base_url,
            connect_timeout_seconds=settings.market_data_connect_timeout_seconds,
            read_timeout_seconds=settings.market_data_read_timeout_seconds,
            max_attempts=settings.market_data_max_attempts,
            retry_base_seconds=settings.market_data_retry_base_seconds,
            retry_max_seconds=settings.market_data_retry_max_seconds,
            max_response_bytes=settings.market_data_max_response_bytes,
            max_concurrency=settings.market_data_max_concurrency,
            cache_ttl_seconds=settings.market_data_cache_ttl_seconds,
            allow_insecure_localhost=settings.market_data_allow_insecure_localhost,
        )
    )
    return AnalyticalRoleHandler(
        role,
        MarketDataCollector(provider, max_concurrency=settings.market_data_max_concurrency),
        RoleDataPlanner(),
        clock,
    )
