from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HubError(Exception):
    code: str
    status_code: int
    detail: str = "request rejected"


class AuthenticationError(HubError):
    pass


class ValidationError(HubError):
    pass


class ConflictError(HubError):
    pass
