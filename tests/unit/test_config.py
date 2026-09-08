from __future__ import annotations

import pytest
from pydantic import ValidationError

from tomiris_hub.core.config import Settings


def _settings(secret: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+asyncpg://unused/unused",
        tomiris_hub_ingest_key_id="current",
        tomiris_hub_ingest_secret=secret,
    )


@pytest.mark.parametrize(
    "secret",
    [
        "CHANGE_ME_012345678901234567890123",
        "placeholder-012345678901234567890",
        "test-secret-012345678901234567890",
        "0123456789abcdef0123456789abcdef",
        "a" * 32,
    ],
)
def test_production_rejects_known_unsafe_secrets(secret: str) -> None:
    with pytest.raises(ValidationError, match="unsafe ingest secret"):
        _settings(secret)


def test_production_accepts_non_placeholder_secret() -> None:
    configured = _settings("K7v!pQ2_zR9@cM4-xT8#nW5+yF3$gH6s")
    assert configured.app_env == "production"


def test_production_rejects_unsafe_previous_rotation_secret() -> None:
    with pytest.raises(ValidationError, match="unsafe ingest secret"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+asyncpg://unused/unused",
            tomiris_hub_ingest_key_id="current",
            tomiris_hub_ingest_secret="K7v!pQ2_zR9@cM4-xT8#nW5+yF3$gH6s",  # noqa: S106
            tomiris_hub_previous_key_id="previous",
            tomiris_hub_previous_secret="placeholder-012345678901234567890",  # noqa: S106
        )
