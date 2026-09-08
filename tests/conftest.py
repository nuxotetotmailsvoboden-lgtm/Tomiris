from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.support import (
    EXPIRED_SNAPSHOT_ID,
    INCOMPATIBLE_SNAPSHOT_ID,
    INVALID_SNAPSHOT_ID,
    NOW,
    VALID_SNAPSHOT_ID,
)
from tomiris_hub.database.models import Agent, MarketSnapshot
from tomiris_hub.database.session import build_engine, build_session_factory


@dataclass(frozen=True)
class DatabaseHarness:
    url: str
    session_factory: async_sessionmaker[AsyncSession]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    if session.testscollected and session.config.pluginmanager.get_plugin("terminalreporter"):
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter.stats.get("skipped"):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture
async def clean_database() -> DatabaseHarness:
    database_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("PostgreSQL TEST_DATABASE_URL is required; SQLite/skips are forbidden")
    engine = build_engine(database_url)
    factory = build_session_factory(engine)
    async with factory() as session, session.begin():
        version = str(await session.scalar(text("SELECT version()")))
        if "PostgreSQL" not in version:
            raise RuntimeError("Phase 01 tests require real PostgreSQL")
        await session.execute(
            text(
                "TRUNCATE notification_outbox, audit_events, signals, used_nonces, "
                "market_snapshots, agents RESTART IDENTITY CASCADE"
            )
        )
        session.add_all(
            [
                Agent(
                    agent_id="TEST_AGENT_001",
                    name="Test Agent",
                    role="test_agent",
                    enabled=True,
                    protocol_version="1.0",
                    capabilities=["signal_ingestion"],
                    criticality="NORMAL",
                    supported_assets=["TEST"],
                    supported_evidence_types=["test"],
                    metadata_json={},
                ),
                Agent(
                    agent_id="OTHER_AGENT_001",
                    name="Other Agent",
                    role="test_agent",
                    enabled=True,
                    protocol_version="1.0",
                    capabilities=["signal_ingestion"],
                    criticality="LOW",
                    supported_assets=["TEST"],
                    supported_evidence_types=["test"],
                    metadata_json={},
                ),
                Agent(
                    agent_id="DISABLED_AGENT_001",
                    name="Disabled Agent",
                    role="test_agent",
                    enabled=False,
                    protocol_version="1.0",
                    capabilities=["signal_ingestion"],
                    criticality="LOW",
                    supported_assets=["TEST"],
                    supported_evidence_types=["test"],
                    metadata_json={},
                ),
            ]
        )
        session.add_all(
            [
                MarketSnapshot(
                    snapshot_id=VALID_SNAPSHOT_ID,
                    created_at=NOW - timedelta(minutes=5),
                    expires_at=NOW + timedelta(minutes=5),
                    status="OPEN",
                    context_version="phase-01-test",
                    metadata_json={"provenance": "system-test"},
                ),
                MarketSnapshot(
                    snapshot_id=EXPIRED_SNAPSHOT_ID,
                    created_at=NOW - timedelta(minutes=10),
                    expires_at=NOW - timedelta(seconds=1),
                    status="OPEN",
                    context_version="phase-01-test",
                    metadata_json={},
                ),
                MarketSnapshot(
                    snapshot_id=INVALID_SNAPSHOT_ID,
                    created_at=NOW - timedelta(minutes=5),
                    expires_at=NOW + timedelta(minutes=5),
                    status="INVALID",
                    context_version="phase-01-test",
                    metadata_json={},
                ),
                MarketSnapshot(
                    snapshot_id=INCOMPATIBLE_SNAPSHOT_ID,
                    created_at=NOW - timedelta(seconds=10),
                    expires_at=NOW + timedelta(minutes=5),
                    status="OPEN",
                    context_version="phase-01-test",
                    metadata_json={},
                ),
            ]
        )
    try:
        yield DatabaseHarness(database_url, factory)
    finally:
        await engine.dispose()
