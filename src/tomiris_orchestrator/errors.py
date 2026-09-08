from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrchestratorError(Exception):
    code: str
    detail: str


class PlanningError(OrchestratorError):
    pass


class EndpointSecurityError(OrchestratorError):
    pass
