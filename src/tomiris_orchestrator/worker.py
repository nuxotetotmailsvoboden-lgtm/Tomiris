from __future__ import annotations

import asyncio

from tomiris_orchestrator.dispatch import DispatchWorker
from tomiris_orchestrator.recovery import RecoveryService


class OrchestratorWorkerLoop:
    def __init__(
        self,
        dispatcher: DispatchWorker,
        recovery: RecoveryService,
        *,
        poll_interval_seconds: float,
    ) -> None:
        self.dispatcher = dispatcher
        self.recovery = recovery
        self.poll_interval_seconds = poll_interval_seconds

    async def run(self, stop: asyncio.Event) -> None:
        await self.recovery.reconcile()
        while not stop.is_set():
            await self.dispatcher.expire_dispatch_deadlines()
            claimed = await self.dispatcher.dispatch_once()
            await self.recovery.reconcile()
            if claimed == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.poll_interval_seconds)
                except TimeoutError:
                    pass
