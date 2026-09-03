from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

from tomiris_hub.core.clock import SystemClock
from tomiris_hub.core.config import get_settings
from tomiris_hub.database.models import MarketSnapshot
from tomiris_hub.database.session import build_engine, build_session_factory


async def main() -> None:
    clock = SystemClock()
    now = clock.now()
    snapshot = MarketSnapshot(
        snapshot_id=uuid4(),
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        status="OPEN",
        context_version="phase-01-test",
        metadata_json={"purpose": "manual_smoke_test"},
    )
    engine = build_engine(get_settings().database_url)
    factory = build_session_factory(engine)
    async with factory() as session, session.begin():
        session.add(snapshot)
    await engine.dispose()
    print(snapshot.snapshot_id)


if __name__ == "__main__":
    asyncio.run(main())
