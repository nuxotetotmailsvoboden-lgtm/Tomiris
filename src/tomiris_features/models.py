from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tomiris_market_data.models import Timeframe, require_utc


class FeatureResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    feature_name: Annotated[str, Field(min_length=1, max_length=64)]
    feature_version: Annotated[str, Field(min_length=1, max_length=32)]
    parameters: dict[str, int | float | str]
    values: dict[str, float]
    timeframe: Timeframe
    as_of: datetime
    valid: bool
    reason_code: Annotated[str | None, Field(max_length=64)] = None

    _utc = field_validator("as_of")(require_utc)

    @field_validator("values")
    @classmethod
    def finite_values(cls, values: dict[str, float]) -> dict[str, float]:
        if len(values) > 10 or any(not math.isfinite(value) for value in values.values()):
            raise ValueError("feature values must be bounded and finite")
        return values
