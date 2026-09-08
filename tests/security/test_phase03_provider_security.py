from __future__ import annotations

import pytest
from pydantic import ValidationError

from tomiris_market_data.binance import BinanceProviderSettings


@pytest.mark.parametrize(
    "url",
    [
        "http://api.binance.com",
        "https://user:password@api.binance.com",
        "https://api.binance.com/path",
        "https://api.binance.com?redirect=evil",
        "https://example.com",
        "file:///etc/passwd",
    ],
)
def test_market_provider_rejects_unsafe_base_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        BinanceProviderSettings(base_url=url)


def test_local_http_requires_explicit_test_override() -> None:
    with pytest.raises(ValidationError):
        BinanceProviderSettings(base_url="http://127.0.0.1:8080")
    settings = BinanceProviderSettings(
        base_url="http://127.0.0.1:8080", allow_insecure_localhost=True
    )
    assert settings.base_url.startswith("http://127.0.0.1")
