from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from tomiris_hub.core.clock import Clock
from tomiris_hub.core.errors import ConflictError, ValidationError
from tomiris_hub.core.security import body_sha256
from tomiris_hub.database.models import Agent, AuditEvent, MarketSnapshot, Nonce, Signal
from tomiris_hub.schemas.signals import SignalEnvelope


class SignalIngestionService:
    def __init__(self, clock: Clock, max_ttl_seconds: int) -> None:
        self.clock = clock
        self.max_ttl_seconds = max_ttl_seconds

    async def ingest(
        self,
        session: AsyncSession,
        envelope: SignalEnvelope,
        nonce: str,
        body: bytes,
        request_id: UUID,
    ) -> None:
        now = self.clock.now()
        if envelope.signal_ttl_seconds > self.max_ttl_seconds:
            raise ValidationError("SIGNAL_TTL_EXCEEDS_MAXIMUM", 422)
        if (
            envelope.analysis_timestamp > now
            or envelope.data_timestamp > envelope.analysis_timestamp
        ):
            raise ValidationError("INVALID_SIGNAL_TIMESTAMPS", 422)
        if envelope.analysis_timestamp + timedelta(seconds=envelope.signal_ttl_seconds) < now:
            raise ValidationError("SIGNAL_EXPIRED", 422)
        payload_hash = body_sha256(body)
        try:
            async with session.begin():
                agent = await session.get(Agent, envelope.agent_id)
                if agent is None:
                    raise ValidationError("UNKNOWN_AGENT", 403)
                if not agent.enabled:
                    raise ValidationError("AGENT_DISABLED", 403)
                if agent.protocol_version != envelope.protocol_version:
                    raise ValidationError("UNSUPPORTED_PROTOCOL_VERSION", 422)
                snapshot = await session.get(MarketSnapshot, envelope.snapshot_id)
                if snapshot is None:
                    raise ValidationError("UNKNOWN_SNAPSHOT", 422)
                if snapshot.status != "OPEN" or snapshot.expires_at <= now:
                    raise ValidationError("SNAPSHOT_NOT_OPEN", 422)
                if (
                    envelope.analysis_timestamp < snapshot.created_at
                    or envelope.analysis_timestamp > snapshot.expires_at
                ):
                    raise ValidationError("SIGNAL_SNAPSHOT_TIME_MISMATCH", 422)
                existing = await session.get(Signal, envelope.message_id)
                if existing is not None:
                    raise ConflictError("DUPLICATE_MESSAGE_ID", 409)
                session.add(Nonce(agent_id=envelope.agent_id, nonce=nonce, received_at=now))
                session.add(
                    Signal(
                        message_id=envelope.message_id,
                        agent_id=envelope.agent_id,
                        agent_run_id=envelope.agent_run_id,
                        snapshot_id=envelope.snapshot_id,
                        protocol_version=envelope.protocol_version,
                        asset=envelope.asset,
                        bias=envelope.bias.value,
                        confidence=envelope.confidence,
                        impact=envelope.impact,
                        time_horizon=envelope.time_horizon,
                        data_timestamp=envelope.data_timestamp,
                        analysis_timestamp=envelope.analysis_timestamp,
                        signal_ttl_seconds=envelope.signal_ttl_seconds,
                        payload_json=envelope.model_dump(mode="json"),
                        payload_hash=payload_hash,
                        received_at=now,
                    )
                )
                session.add(
                    AuditEvent(
                        occurred_at=now,
                        event_type="SIGNAL_INGESTION",
                        outcome="ACCEPTED",
                        reason_code=None,
                        request_id=request_id,
                        agent_id=envelope.agent_id,
                        message_id=envelope.message_id,
                        payload_hash=payload_hash,
                        metadata_json={"snapshot_id": str(envelope.snapshot_id)},
                    )
                )
        except IntegrityError as exc:
            raise ConflictError("REPLAY_OR_DUPLICATE", 409) from exc

    async def record_rejection(
        self,
        session: AsyncSession,
        request_id: UUID,
        reason: str,
        body: bytes,
        agent_id: str | None,
    ) -> None:
        try:
            async with session.begin():
                session.add(
                    AuditEvent(
                        occurred_at=self.clock.now(),
                        event_type="SIGNAL_INGESTION",
                        outcome="REJECTED",
                        reason_code=reason,
                        request_id=request_id,
                        agent_id=agent_id,
                        message_id=None,
                        payload_hash=body_sha256(body),
                        metadata_json={},
                    )
                )
        except SQLAlchemyError:
            await session.rollback()
