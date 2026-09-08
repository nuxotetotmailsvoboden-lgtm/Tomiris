from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from tomiris_core_contracts.orchestration import AnalysisTaskAck
from tomiris_hub.core.errors import AuthenticationError, ConflictError


@dataclass(frozen=True)
class AcceptedTask:
    body_hash: str
    ack: AnalysisTaskAck


class RuntimeTaskStore:
    """Bounded process-local replay/idempotency state for an unprivileged Space."""

    def __init__(self, max_entries: int = 10_000) -> None:
        self.max_entries = max_entries
        self._nonces: dict[str, datetime] = {}
        self._tasks: dict[UUID, AcceptedTask] = {}
        self._lock = asyncio.Lock()

    async def accept(
        self,
        *,
        nonce: str,
        nonce_expires_at: datetime,
        now: datetime,
        task_id: UUID,
        body_hash: str,
        ack: AnalysisTaskAck,
    ) -> tuple[AnalysisTaskAck, bool]:
        async with self._lock:
            self._nonces = {known: expiry for known, expiry in self._nonces.items() if expiry > now}
            if nonce in self._nonces:
                raise AuthenticationError("COMMAND_REPLAY", 409)
            self._nonces[nonce] = nonce_expires_at
            existing = self._tasks.get(task_id)
            if existing is not None:
                if existing.body_hash != body_hash:
                    raise ConflictError("TASK_DUPLICATE_CONFLICT", 409)
                return existing.ack, False
            if len(self._tasks) >= self.max_entries:
                oldest = next(iter(self._tasks))
                del self._tasks[oldest]
            self._tasks[task_id] = AcceptedTask(body_hash, ack)
            return ack, True
