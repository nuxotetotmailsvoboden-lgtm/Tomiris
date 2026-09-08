from __future__ import annotations

from typing import Protocol

from tomiris_agent_sdk.client import HubClient
from tomiris_core_contracts.signals import SignalEnvelope


class SignalSink(Protocol):
    async def send(self, signal: SignalEnvelope) -> bool: ...


class HubSignalSink:
    def __init__(self, client: HubClient) -> None:
        self.client = client

    async def send(self, signal: SignalEnvelope) -> bool:
        response = await self.client.send_signal(signal.model_dump(mode="json"))
        return response.status_code == 202


class NullSignalSink:
    async def send(self, signal: SignalEnvelope) -> bool:
        del signal
        return True
