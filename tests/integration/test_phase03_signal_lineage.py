from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from tests.conftest import DatabaseHarness
from tests.support import NOW, encode_payload, hub_client, signal_payload, signed_headers

from tomiris_hub.database.models import Signal


def analytical_payload(**changes: object) -> dict[str, object]:
    payload = signal_payload(
        role_id="test.analytical.v1",
        role_version="1.0.0",
        config_version="test-config.v1",
        feature_pipeline_version="test-pipeline.v1",
        analysis_schema_version="1",
        data_provider="fixture",
        data_as_of=NOW.isoformat(),
        confidence_model_version="deterministic-agreement.v1",
    )
    payload.update(changes)
    return payload


async def test_analytical_lineage_is_ingested_as_first_class_columns(
    clean_database: DatabaseHarness,
) -> None:
    payload = analytical_payload()
    body = encode_payload(payload)
    async with hub_client(clean_database.url) as client:
        response = await client.post("/v1/signals", content=body, headers=signed_headers(body))
    assert response.status_code == 202
    async with clean_database.session_factory() as session:
        stored = await session.scalar(select(Signal))
    assert stored is not None
    assert stored.role_id == "test.analytical.v1"
    assert stored.role_version == "1.0.0"
    assert stored.config_version == "test-config.v1"
    assert stored.feature_pipeline_version == "test-pipeline.v1"
    assert stored.analysis_schema_version == "1"
    assert stored.data_provider == "fixture"
    assert stored.data_as_of == NOW
    assert stored.confidence_model_version == "deterministic-agreement.v1"


async def test_partial_or_lookahead_lineage_is_rejected(
    clean_database: DatabaseHarness,
) -> None:
    partial = signal_payload(role_id="test.analytical.v1")
    partial_body = encode_payload(partial)
    future = analytical_payload(data_as_of=(NOW + timedelta(seconds=1)).isoformat())
    future_body = encode_payload(future)
    async with hub_client(clean_database.url) as client:
        partial_response = await client.post(
            "/v1/signals", content=partial_body, headers=signed_headers(partial_body)
        )
        future_response = await client.post(
            "/v1/signals", content=future_body, headers=signed_headers(future_body)
        )
    assert partial_response.status_code == 422
    assert future_response.status_code == 422
