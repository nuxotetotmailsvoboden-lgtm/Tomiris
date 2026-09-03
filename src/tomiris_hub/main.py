from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tomiris_hub.api.health import router as health_router
from tomiris_hub.api.signals import router as signals_router
from tomiris_hub.core.clock import SystemClock
from tomiris_hub.core.config import Settings, get_settings
from tomiris_hub.core.security import SharedSecretProvider
from tomiris_hub.database.session import build_engine, build_session_factory
from tomiris_hub.services.authentication import HmacAuthenticator
from tomiris_hub.services.signal_ingestion import SignalIngestionService


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(active_settings.database_url)
        app.state.engine = engine
        app.state.session_factory = build_session_factory(engine)
        app.state.settings = active_settings
        app.state.clock = SystemClock()
        provider = SharedSecretProvider(
            active_settings.tomiris_hub_ingest_key_id,
            active_settings.tomiris_hub_ingest_secret.get_secret_value(),
            active_settings.tomiris_hub_previous_key_id,
            active_settings.tomiris_hub_previous_secret.get_secret_value()
            if active_settings.tomiris_hub_previous_secret
            else None,
        )
        app.state.authenticator = HmacAuthenticator(
            provider, app.state.clock, active_settings.auth_max_clock_skew_seconds
        )
        app.state.ingestion = SignalIngestionService(
            app.state.clock, active_settings.max_signal_ttl_seconds
        )
        yield
        await engine.dispose()

    app = FastAPI(
        title=active_settings.app_name, version=active_settings.app_version, lifespan=lifespan
    )
    app.include_router(health_router)
    app.include_router(signals_router)
    return app


app = create_app()
