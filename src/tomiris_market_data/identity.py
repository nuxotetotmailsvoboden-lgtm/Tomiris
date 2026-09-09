from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketType(StrEnum):
    SPOT = "SPOT"
    USDT_M_FUTURES = "USDT_M_FUTURES"
    COIN_M_FUTURES = "COIN_M_FUTURES"
    OPTIONS = "OPTIONS"
    TRADFI = "TRADFI"


class ContractType(StrEnum):
    SPOT = "SPOT"
    PERPETUAL = "PERPETUAL"
    DELIVERY = "DELIVERY"


class CanonicalInstrument(BaseModel):
    """Immutable identity that prevents same-symbol cross-market contamination."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    venue: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_-]{1,31}$")]
    market_type: MarketType
    symbol: Annotated[str, Field(pattern=r"^[A-Z0-9_./-]{2,32}$")]
    base_asset: Annotated[str, Field(pattern=r"^[A-Z0-9]{1,16}$")]
    quote_asset: Annotated[str, Field(pattern=r"^[A-Z0-9]{1,16}$")]
    contract_type: ContractType

    @model_validator(mode="after")
    def validate_market_contract(self) -> CanonicalInstrument:
        if self.market_type == MarketType.SPOT and self.contract_type != ContractType.SPOT:
            raise ValueError("spot instrument must use SPOT contract type")
        if self.market_type != MarketType.SPOT and self.contract_type == ContractType.SPOT:
            raise ValueError("derivatives instrument cannot use SPOT contract type")
        return self

    @property
    def instrument_id(self) -> str:
        return f"{self.venue}:{self.market_type.value}:{self.symbol}"

    @classmethod
    def binance_spot(cls, symbol: str, base_asset: str, quote_asset: str) -> CanonicalInstrument:
        return cls(
            venue="BINANCE",
            market_type=MarketType.SPOT,
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            contract_type=ContractType.SPOT,
        )

    @classmethod
    def binance_usdt_m(
        cls,
        symbol: str,
        base_asset: str,
        quote_asset: str = "USDT",
        contract_type: ContractType = ContractType.PERPETUAL,
    ) -> CanonicalInstrument:
        return cls(
            venue="BINANCE",
            market_type=MarketType.USDT_M_FUTURES,
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            contract_type=contract_type,
        )


def infer_binance_assets(
    symbol: str, quote_assets: tuple[str, ...] = ("USDT", "USDC", "BTC")
) -> tuple[str, str]:
    normalized = symbol.upper()
    for quote in quote_assets:
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized[: -len(quote)], quote
    raise ValueError(f"cannot infer base/quote assets for {symbol}")
