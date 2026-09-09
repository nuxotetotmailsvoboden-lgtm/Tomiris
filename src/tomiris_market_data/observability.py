from __future__ import annotations

import logging

from tomiris_market_data.contracts import NormalizedMarketEvent
from tomiris_market_data.quality import MarketDataQualityReport
from tomiris_market_data.snapshot import VerifiedMarketSnapshotManifest


def log_market_event(
    logger: logging.Logger,
    event: NormalizedMarketEvent,
    quality: MarketDataQualityReport,
) -> None:
    age_ms = (quality.observed_at - event.event_time).total_seconds() * 1_000
    logger.info(
        "market_event_validated",
        extra={
            "provider": event.provider,
            "instrument_id": event.instrument_id,
            "data_type": event.data_type.value,
            "sequence": event.sequence,
            "event_time": event.event_time.isoformat(),
            "received_at": event.received_at.isoformat(),
            "age_ms": max(0.0, age_ms),
            "quality_state": quality.overall_state.value,
            "reason_code": quality.reason_codes[0] if quality.reason_codes else None,
        },
    )


def log_snapshot(logger: logging.Logger, manifest: VerifiedMarketSnapshotManifest) -> None:
    logger.info(
        "market_snapshot_created",
        extra={
            "snapshot_id": str(manifest.snapshot_id),
            "as_of": manifest.as_of.isoformat(),
            "instrument_set": manifest.instruments,
            "quality_state": manifest.quality_state.value,
            "source_set": manifest.providers,
            "fingerprint": manifest.content_fingerprint,
            "safe_for_analysis": manifest.safe_for_analysis,
        },
    )
