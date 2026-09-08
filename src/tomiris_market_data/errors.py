from __future__ import annotations


class MarketDataError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProviderError(MarketDataError):
    pass


class DataValidationError(MarketDataError):
    pass
