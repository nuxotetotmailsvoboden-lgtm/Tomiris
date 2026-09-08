from __future__ import annotations

from enum import StrEnum


class TriggerType(StrEnum):
    MANUAL = "MANUAL"
    TEST = "TEST"


class SchedulerTrigger:
    """Phase 02 trigger abstraction. Market and timed triggers are intentionally absent."""

    @staticmethod
    def validate(value: str) -> TriggerType:
        return TriggerType(value)
