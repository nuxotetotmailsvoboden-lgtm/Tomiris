from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"
    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    protocol_version: Mapped[str] = mapped_column(String(16), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    criticality: Mapped[str] = mapped_column(String(16), nullable=False, default="NORMAL")
    supported_assets: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    supported_evidence_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "criticality IN ('LOW','NORMAL','HIGH','CRITICAL')",
            name="ck_agent_criticality",
        ),
    )


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    context_version: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','CLOSED','EXPIRED','INVALID')", name="ck_snapshot_status"
        ),
    )


class Nonce(Base):
    __tablename__ = "used_nonces"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), nullable=False)
    nonce: Mapped[str] = mapped_column(String(256), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("agent_id", "nonce", name="uq_nonce_agent_nonce"),)


class Signal(Base):
    __tablename__ = "signals"
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), nullable=False)
    agent_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_snapshots.snapshot_id"), nullable=False
    )
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    protocol_version: Mapped[str] = mapped_column(String(16), nullable=False)
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    bias: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(64), nullable=False)
    data_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analysis_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_signal_confidence"),
        CheckConstraint("impact >= 0 AND impact <= 100", name="ck_signal_impact"),
        CheckConstraint("signal_ttl_seconds > 0", name="ck_signal_ttl"),
        CheckConstraint("bias IN ('LONG','SHORT','NEUTRAL','ABSTAIN')", name="ck_signal_bias"),
        Index("ix_signals_agent_received", "agent_id", "received_at"),
        Index("ix_signals_snapshot", "snapshot_id"),
        Index("ix_signals_correlation", "correlation_id"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(64))
    message_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    snapshot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    __table_args__ = (
        Index("ix_audit_request", "request_id"),
        Index("ix_audit_agent_occurred", "agent_id", "occurred_at"),
        Index("ix_audit_message", "message_id"),
        Index("ix_audit_correlation", "correlation_id", "occurred_at"),
    )


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    notification_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column("payload", JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','RETRY','FAILED','DEAD_LETTER')",
            name="ck_notification_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_notification_attempt_count"),
        Index("ix_notification_dispatch", "status", "next_attempt_at"),
        Index("ix_notification_event", "event_id"),
    )
