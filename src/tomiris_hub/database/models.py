from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_tasks.task_id"))
    orchestration_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("orchestration_runs.orchestration_run_id")
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
        CheckConstraint(
            "(task_id IS NULL AND orchestration_run_id IS NULL) OR "
            "(task_id IS NOT NULL AND orchestration_run_id IS NOT NULL)",
            name="ck_signal_task_lineage",
        ),
        Index("ix_signals_agent_received", "agent_id", "received_at"),
        Index("ix_signals_snapshot", "snapshot_id"),
        Index("ix_signals_correlation", "correlation_id"),
        Index("uq_signals_task_result", "task_id", unique=True),
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


class AgentEndpoint(Base):
    __tablename__ = "agent_endpoints"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), primary_key=True)
    endpoint_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False, default="HTTP")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint("transport IN ('HTTP')", name="ck_agent_endpoint_transport"),
        CheckConstraint(
            "environment IN ('TEST','DEVELOPMENT','PRODUCTION')",
            name="ck_agent_endpoint_environment",
        ),
    )


class AgentRuntimeState(Base):
    __tablename__ = "agent_runtime_states"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), primary_key=True)
    availability: Mapped[str] = mapped_column(String(16), nullable=False, default="UNKNOWN")
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    circuit_state: Mapped[str] = mapped_column(String(16), nullable=False, default="CLOSED")
    circuit_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "availability IN ('UNKNOWN','HEALTHY','DEGRADED','UNAVAILABLE')",
            name="ck_agent_runtime_availability",
        ),
        CheckConstraint(
            "circuit_state IN ('CLOSED','OPEN','HALF_OPEN')",
            name="ck_agent_runtime_circuit",
        ),
        CheckConstraint("consecutive_failures >= 0", name="ck_agent_runtime_failures"),
        Index("ix_agent_runtime_availability", "availability"),
    )


class OrchestrationRun(Base):
    __tablename__ = "orchestration_runs"
    orchestration_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_snapshots.snapshot_id"), nullable=False
    )
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CREATED")
    outcome: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collection_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    __table_args__ = (
        CheckConstraint("trigger_type IN ('MANUAL','TEST')", name="ck_run_trigger"),
        CheckConstraint(
            "status IN ('CREATED','DISPATCHING','COLLECTING','FULL','DEGRADED',"
            "'CRITICAL','FAILED','TIMED_OUT','CANCELLED')",
            name="ck_run_status",
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('FULL','DEGRADED','CRITICAL','INSUFFICIENT_DATA')",
            name="ck_run_outcome",
        ),
        CheckConstraint("collection_deadline > created_at", name="ck_run_deadline"),
        Index("ix_orchestration_runs_status", "status"),
        Index("ix_orchestration_runs_snapshot", "snapshot_id"),
    )


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    orchestration_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("orchestration_runs.orchestration_run_id"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_snapshots.snapshot_id"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), nullable=False)
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    required_capability: Mapped[str] = mapped_column(String(64), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    criticality: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatch_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatch_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signal_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context_json: Mapped[dict[str, object]] = mapped_column(
        "context", JSONB, nullable=False, default=dict
    )
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','DISPATCHING','ACKNOWLEDGED','WAITING_SIGNAL',"
            "'SIGNAL_RECEIVED','RETRY','TIMED_OUT','FAILED','CANCELLED','SKIPPED')",
            name="ck_agent_task_status",
        ),
        CheckConstraint(
            "criticality IN ('LOW','NORMAL','HIGH','CRITICAL')",
            name="ck_agent_task_criticality",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_agent_task_attempts"),
        CheckConstraint("priority >= 0 AND priority <= 100", name="ck_agent_task_priority"),
        CheckConstraint(
            "dispatch_deadline > created_at AND signal_deadline >= dispatch_deadline",
            name="ck_agent_task_deadlines",
        ),
        UniqueConstraint(
            "orchestration_run_id",
            "agent_id",
            "asset",
            "required_capability",
            name="uq_agent_task_assignment",
        ),
        Index("ix_agent_tasks_dispatch", "status", "dispatch_after"),
        Index("ix_agent_tasks_run", "orchestration_run_id"),
        Index("ix_agent_tasks_agent", "agent_id"),
        Index("ix_agent_tasks_snapshot", "snapshot_id"),
        Index("ix_agent_tasks_lease", "lease_until"),
    )
