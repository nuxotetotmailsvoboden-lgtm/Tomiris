from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tomiris_core_contracts.signals import EvidenceItem
from tomiris_core_contracts.snapshots import MarketSnapshot, SnapshotStatus
from tomiris_hub.schemas.signals import SignalEnvelope


def valid_payload() -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    return {
        "protocol_version": "1.0",
        "message_id": str(uuid4()),
        "agent_id": "TEST_AGENT_001",
        "agent_run_id": str(uuid4()),
        "snapshot_id": str(uuid4()),
        "asset": "TEST",
        "bias": "LONG",
        "confidence": 50,
        "impact": 10,
        "time_horizon": "test",
        "evidence": [],
        "risk_flags": [],
        "data_timestamp": now,
        "analysis_timestamp": now,
        "signal_ttl_seconds": 30,
        "metadata": {},
    }


def test_confidence_bounds() -> None:
    payload = valid_payload()
    payload["confidence"] = 101
    with pytest.raises(ValidationError):
        SignalEnvelope.model_validate(payload)


def test_extra_fields_rejected() -> None:
    payload = valid_payload()
    payload["trade_now"] = True
    with pytest.raises(ValidationError):
        SignalEnvelope.model_validate(payload)


def test_evidence_provider_is_backward_compatible() -> None:
    now = datetime.now(UTC)
    evidence = EvidenceItem(
        evidence_type="test",
        summary="legacy producer",
        source_type="fixture",
        source_id="legacy-1",
        observed_at=now,
        source_timestamp=now,
    )
    assert evidence.provider == "unknown"


def test_market_snapshot_contract_rejects_invalid_window() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        MarketSnapshot(
            snapshot_id=uuid4(),
            created_at=now,
            expires_at=now,
            status=SnapshotStatus.OPEN,
            context_version="test",
        )
