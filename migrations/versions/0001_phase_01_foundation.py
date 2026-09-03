"""phase 01 secure hub storage"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_phase_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("protocol_version", sa.String(16), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_table(
        "market_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("context_version", sa.String(32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN','CLOSED','EXPIRED','INVALID')", name="ck_snapshot_status"
        ),
    )
    op.create_table(
        "nonces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("agents.agent_id"), nullable=False),
        sa.Column("nonce", sa.String(256), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "nonce", name="uq_nonce_agent_nonce"),
    )
    op.create_table(
        "signals",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("agents.agent_id"), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market_snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column("protocol_version", sa.String(16), nullable=False),
        sa.Column("asset", sa.String(32), nullable=False),
        sa.Column("bias", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("impact", sa.Integer(), nullable=False),
        sa.Column("time_horizon", sa.String(64), nullable=False),
        sa.Column("data_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_signal_confidence"),
        sa.CheckConstraint("impact >= 0 AND impact <= 100", name="ck_signal_impact"),
        sa.CheckConstraint("signal_ttl_seconds > 0", name="ck_signal_ttl"),
        sa.CheckConstraint("bias IN ('LONG','SHORT','NEUTRAL','ABSTAIN')", name="ck_signal_bias"),
    )
    op.create_index("ix_signals_agent_received", "signals", ["agent_id", "received_at"])
    op.create_index("ix_signals_snapshot", "signals", ["snapshot_id"])
    op.create_table(
        "audit_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(64)),
        sa.Column("message_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payload_hash", sa.String(64)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_audit_request", "audit_events", ["request_id"])
    op.create_index("ix_audit_agent_occurred", "audit_events", ["agent_id", "occurred_at"])
    op.create_index("ix_audit_message", "audit_events", ["message_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("signals")
    op.drop_table("nonces")
    op.drop_table("market_snapshots")
    op.drop_table("agents")
