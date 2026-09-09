from __future__ import annotations

import time
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tomiris_market_data.capabilities import MarketDataType
from tomiris_market_data.contracts import NormalizedMarketEvent, OHLCVWindow, OrderBookSnapshot
from tomiris_market_data.errors import SnapshotValidationError
from tomiris_market_data.identity import CanonicalInstrument
from tomiris_market_data.models import DataQualityOutcome, require_utc
from tomiris_market_data.plane_metrics import MarketDataPlaneMetrics
from tomiris_market_data.quality import (
    MarketDataQualityEngine,
    MarketDataQualityReport,
    QualityDimension,
    QualityDimensionResult,
)
from tomiris_market_data.serialization import canonical_sha256
from tomiris_market_data.store import RecentMarketEventStore
from tomiris_market_data.time import (
    ClockDriftMeasurement,
    SystemUTCClock,
    TimeSource,
    TimeSyncState,
)


class SnapshotRequirementItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument: CanonicalInstrument
    data_type: MarketDataType
    required: bool = True
    max_age_seconds: float = Field(gt=0, le=604_800)
    minimum_depth: int | None = Field(default=None, ge=1, le=5_000)
    qualifier: Annotated[str | None, Field(max_length=32)] = None

    @model_validator(mode="after")
    def depth_only_for_book(self) -> SnapshotRequirementItem:
        if self.minimum_depth is not None and self.data_type != MarketDataType.ORDER_BOOK_SNAPSHOT:
            raise ValueError("minimum depth is only valid for order-book snapshots")
        if self.data_type == MarketDataType.OHLCV and self.qualifier is None:
            raise ValueError("OHLCV snapshot requirement needs a timeframe qualifier")
        return self


class SnapshotRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Annotated[str, Field(min_length=1, max_length=32)] = "snapshot.v1"
    items: Annotated[tuple[SnapshotRequirementItem, ...], Field(min_length=1, max_length=500)]
    max_temporal_skew_seconds: float = Field(default=5, ge=0, le=86_400)
    query_limit_per_item: int = Field(default=1_000, ge=1, le=10_000)

    @model_validator(mode="after")
    def unique_requirements(self) -> SnapshotRequirement:
        keys = {
            (item.instrument.instrument_id, item.data_type, item.qualifier) for item in self.items
        }
        if len(keys) != len(self.items):
            raise ValueError("snapshot requirements must be unique")
        return self


class SnapshotComponentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    data_type: MarketDataType
    qualifier: str | None = None
    provider: str
    event_id: str
    event_time: datetime
    received_at: datetime
    first_available_event_time: datetime
    last_available_event_time: datetime
    schema_version: str
    quality_state: DataQualityOutcome
    provenance: str
    content_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    _utc = field_validator(
        "event_time", "received_at", "first_available_event_time", "last_available_event_time"
    )(require_utc)


class VerifiedMarketSnapshotManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^1$")] = "1"
    snapshot_id: UUID
    as_of: datetime
    created_at: datetime
    policy_version: str
    instruments: tuple[str, ...]
    providers: tuple[str, ...]
    data_types: tuple[MarketDataType, ...]
    components: tuple[SnapshotComponentManifest, ...]
    missing_required: tuple[str, ...] = ()
    missing_optional: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    quality_state: DataQualityOutcome
    safe_for_analysis: bool
    temporal_skew_seconds: float = Field(ge=0)
    provenance_references: tuple[str, ...]
    content_fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    _utc = field_validator("as_of", "created_at")(require_utc)

    @model_validator(mode="after")
    def enforce_veto(self) -> VerifiedMarketSnapshotManifest:
        if self.created_at < self.as_of:
            raise ValueError("snapshot creation cannot precede logical cutoff")
        if (
            self.quality_state
            in {
                DataQualityOutcome.INVALID,
                DataQualityOutcome.INSUFFICIENT,
            }
            and self.safe_for_analysis
        ):
            raise ValueError("unsafe snapshot cannot be marked decision-grade")
        return self


class VerifiedMarketSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: VerifiedMarketSnapshotManifest
    events: tuple[NormalizedMarketEvent, ...]

    @model_validator(mode="after")
    def manifest_matches_events(self) -> VerifiedMarketSnapshot:
        components = {item.event_id: item for item in self.manifest.components}
        events = {item.event_id: item for item in self.events}
        if set(components) != set(events):
            raise ValueError("snapshot events do not match manifest")
        for event_id, event in events.items():
            component = components[event_id]
            if (
                component.content_hash != canonical_sha256(event)
                or component.instrument_id != event.instrument_id
                or component.data_type != event.data_type
                or component.provider != event.provider
                or component.event_time != event.event_time
            ):
                raise ValueError("snapshot component integrity check failed")
        return self

    def require_analysis_safe(self) -> None:
        if not self.manifest.safe_for_analysis:
            raise SnapshotValidationError(
                "SNAPSHOT_NOT_ANALYSIS_SAFE",
                ",".join(self.manifest.reason_codes) or "snapshot quality veto",
            )


class VerifiedMarketSnapshotBuilder:
    def __init__(
        self,
        store: RecentMarketEventStore,
        *,
        clock: TimeSource | None = None,
        quality_engine: MarketDataQualityEngine | None = None,
        metrics: MarketDataPlaneMetrics | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or SystemUTCClock()
        self.quality_engine = quality_engine or MarketDataQualityEngine()
        self.metrics = metrics or MarketDataPlaneMetrics()

    async def build(
        self,
        *,
        snapshot_id: UUID,
        as_of: datetime,
        requirement: SnapshotRequirement,
        quality_reports: dict[str, MarketDataQualityReport],
        clock_measurements: tuple[ClockDriftMeasurement, ...] = (),
    ) -> VerifiedMarketSnapshot:
        require_utc(as_of)
        started = time.perf_counter()
        selected: list[NormalizedMarketEvent] = []
        components: list[SnapshotComponentManifest] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []
        states: list[DataQualityOutcome] = []
        reasons: list[str] = []

        for item in requirement.items:
            events = await self.store.query(
                instrument_id=item.instrument.instrument_id,
                data_types=frozenset({item.data_type}),
                as_of=as_of,
                limit=requirement.query_limit_per_item,
            )
            events = tuple(event for event in events if _matches_qualifier(event, item.qualifier))
            suffix = f":{item.qualifier}" if item.qualifier is not None else ""
            key = f"{item.instrument.instrument_id}/{item.data_type.value}{suffix}"
            if not events:
                (missing_required if item.required else missing_optional).append(key)
                states.append(
                    DataQualityOutcome.INSUFFICIENT
                    if item.required
                    else DataQualityOutcome.DEGRADED
                )
                reasons.append(
                    "REQUIRED_DATA_MISSING" if item.required else "OPTIONAL_DATA_MISSING"
                )
                continue
            ordered = tuple(sorted(events, key=lambda event: (event.event_time, event.event_id)))
            event = ordered[-1]
            report = quality_reports.get(event.event_id)
            if report is None:
                report = self._missing_quality_report(event, as_of)
            item_state = report.overall_state
            reasons.extend(report.reason_codes)
            age = (as_of - event.event_time).total_seconds()
            if age < 0:
                raise SnapshotValidationError(
                    "LOOKAHEAD_DETECTED", "event after logical cutoff reached snapshot builder"
                )
            if age > item.max_age_seconds:
                item_state = (
                    DataQualityOutcome.INVALID if item.required else DataQualityOutcome.DEGRADED
                )
                reasons.append("DATA_STALE")
            if item.minimum_depth is not None:
                payload = event.payload
                depth = (
                    min(len(payload.bids), len(payload.asks))
                    if isinstance(payload, OrderBookSnapshot)
                    else 0
                )
                if depth < item.minimum_depth:
                    item_state = (
                        DataQualityOutcome.INSUFFICIENT
                        if item.required
                        else DataQualityOutcome.DEGRADED
                    )
                    reasons.append("ORDER_BOOK_DEPTH_INSUFFICIENT")
            if not report.safe_for_analysis and item.required:
                item_state = max((item_state, DataQualityOutcome.INVALID), key=_quality_severity)
            states.append(item_state)
            self.metrics.observe(
                "market_data_age_seconds",
                event.provider,
                event.instrument.market_type,
                event.data_type,
                age,
            )
            if item_state == DataQualityOutcome.INVALID:
                self.metrics.increment(
                    "market_quality_invalid_total",
                    event.provider,
                    event.instrument.market_type,
                    event.data_type,
                )
            selected.append(event)
            components.append(
                SnapshotComponentManifest(
                    instrument_id=event.instrument_id,
                    data_type=event.data_type,
                    qualifier=item.qualifier,
                    provider=event.provider,
                    event_id=event.event_id,
                    event_time=event.event_time,
                    received_at=event.received_at,
                    first_available_event_time=ordered[0].event_time,
                    last_available_event_time=ordered[-1].event_time,
                    schema_version=event.schema_version,
                    quality_state=item_state,
                    provenance=event.source.provenance,
                    content_hash=canonical_sha256(event),
                )
            )

        event_times = [event.event_time for event in selected]
        skew = (
            (max(event_times) - min(event_times)).total_seconds() if len(event_times) > 1 else 0.0
        )
        if skew > requirement.max_temporal_skew_seconds:
            states.append(DataQualityOutcome.INVALID)
            reasons.append("TEMPORAL_SKEW_EXCEEDED")
        if any(measurement.state == TimeSyncState.UNSAFE for measurement in clock_measurements):
            states.append(DataQualityOutcome.INVALID)
            reasons.append("CLOCK_DRIFT_UNSAFE")
        elif any(measurement.state == TimeSyncState.DEGRADED for measurement in clock_measurements):
            states.append(DataQualityOutcome.DEGRADED)
            reasons.append("CLOCK_DRIFT_DEGRADED")
        for measurement in clock_measurements:
            self.metrics.observe(
                "market_clock_drift_ms",
                measurement.provider,
                requirement.items[0].instrument.market_type,
                requirement.items[0].data_type,
                measurement.clock_offset_ms,
            )
        overall = max(states, key=_quality_severity) if states else DataQualityOutcome.INSUFFICIENT
        ordered_events = tuple(
            sorted(selected, key=lambda event: (event.instrument_id, event.data_type))
        )
        ordered_components = tuple(
            sorted(
                components,
                key=lambda item: (item.instrument_id, item.data_type, item.qualifier or ""),
            )
        )
        reason_codes = tuple(dict.fromkeys(reasons))
        fingerprint_material = {
            "schema_version": "1",
            "as_of": as_of,
            "policy_version": requirement.policy_version,
            "components": ordered_components,
            "missing_required": tuple(sorted(missing_required)),
            "missing_optional": tuple(sorted(missing_optional)),
            "reason_codes": reason_codes,
            "quality_state": overall,
        }
        manifest = VerifiedMarketSnapshotManifest(
            snapshot_id=snapshot_id,
            as_of=as_of,
            created_at=self.clock.now(),
            policy_version=requirement.policy_version,
            instruments=tuple(
                sorted({item.instrument.instrument_id for item in requirement.items})
            ),
            providers=tuple(sorted({event.provider for event in ordered_events})),
            data_types=tuple(sorted({item.data_type for item in requirement.items})),
            components=ordered_components,
            missing_required=tuple(sorted(missing_required)),
            missing_optional=tuple(sorted(missing_optional)),
            reason_codes=reason_codes,
            quality_state=overall,
            safe_for_analysis=overall in {DataQualityOutcome.VALID, DataQualityOutcome.DEGRADED}
            and not missing_required,
            temporal_skew_seconds=skew,
            provenance_references=tuple(
                sorted({component.provenance for component in ordered_components})
            ),
            content_fingerprint=canonical_sha256(fingerprint_material),
        )
        metric_name = (
            "market_snapshot_build_total"
            if manifest.safe_for_analysis
            else "market_snapshot_failure_total"
        )
        first_item = requirement.items[0]
        self.metrics.increment(
            metric_name,
            manifest.providers[0] if manifest.providers else "unavailable",
            first_item.instrument.market_type,
            first_item.data_type,
        )
        self.metrics.observe(
            "market_snapshot_latency_ms",
            manifest.providers[0] if manifest.providers else "unavailable",
            first_item.instrument.market_type,
            first_item.data_type,
            (time.perf_counter() - started) * 1_000,
        )
        return VerifiedMarketSnapshot(manifest=manifest, events=ordered_events)

    def _missing_quality_report(
        self, event: NormalizedMarketEvent, observed_at: datetime
    ) -> MarketDataQualityReport:
        return self.quality_engine.evaluate(
            instrument=event.instrument,
            data_type=event.data_type,
            provider=event.provider,
            observed_at=observed_at,
            dimensions=(
                QualityDimensionResult(
                    dimension=QualityDimension.SCHEMA_INTEGRITY,
                    state=DataQualityOutcome.INVALID,
                    reason_codes=("QUALITY_REPORT_MISSING",),
                ),
            ),
            force_unsafe=True,
        )


def _quality_severity(value: DataQualityOutcome) -> int:
    return {
        DataQualityOutcome.VALID: 0,
        DataQualityOutcome.DEGRADED: 1,
        DataQualityOutcome.INSUFFICIENT: 2,
        DataQualityOutcome.INVALID: 3,
    }[value]


def _matches_qualifier(event: NormalizedMarketEvent, qualifier: str | None) -> bool:
    if qualifier is None:
        return True
    return isinstance(event.payload, OHLCVWindow) and event.payload.timeframe.value == qualifier
