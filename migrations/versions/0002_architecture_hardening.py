"""architecture boundaries, provenance and notification outbox"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_architecture_hardening"
down_revision = "0001_phase_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("nonces", "used_nonces")

    op.add_column(
        "agents",
        sa.Column(
            "capabilities",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "agents",
        sa.Column("criticality", sa.String(16), nullable=False, server_default="NORMAL"),
    )
    op.add_column(
        "agents",
        sa.Column(
            "supported_assets",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "supported_evidence_types",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_agent_criticality",
        "agents",
        "criticality IN ('LOW','NORMAL','HIGH','CRITICAL')",
    )
    op.alter_column(
        "agents",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column(
        "agents",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    op.add_column("signals", sa.Column("correlation_id", postgresql.UUID(as_uuid=True)))
    op.add_column("signals", sa.Column("causation_id", postgresql.UUID(as_uuid=True)))
    op.execute("UPDATE signals SET correlation_id = message_id WHERE correlation_id IS NULL")
    op.alter_column("signals", "correlation_id", nullable=False)
    op.create_index("ix_signals_correlation", "signals", ["correlation_id"])

    op.add_column("audit_events", sa.Column("snapshot_id", postgresql.UUID(as_uuid=True)))
    op.add_column("audit_events", sa.Column("correlation_id", postgresql.UUID(as_uuid=True)))
    op.add_column("audit_events", sa.Column("causation_id", postgresql.UUID(as_uuid=True)))
    op.execute("UPDATE audit_events SET correlation_id = request_id WHERE correlation_id IS NULL")
    op.alter_column("audit_events", "correlation_id", nullable=False)
    op.create_index("ix_audit_correlation", "audit_events", ["correlation_id", "occurred_at"])

    op.create_table(
        "notification_outbox",
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True)),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("recipient_ref", sa.String(256), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(256), nullable=False, unique=True),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint(
            "status IN ('PENDING','SENDING','SENT','RETRY','FAILED','DEAD_LETTER')",
            name="ck_notification_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_notification_attempt_count"),
    )
    op.create_index(
        "ix_notification_dispatch",
        "notification_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index("ix_notification_event", "notification_outbox", ["event_id"])


def downgrade() -> None:
    op.drop_table("notification_outbox")
    op.drop_index("ix_audit_correlation", table_name="audit_events")
    op.drop_column("audit_events", "causation_id")
    op.drop_column("audit_events", "correlation_id")
    op.drop_column("audit_events", "snapshot_id")
    op.drop_index("ix_signals_correlation", table_name="signals")
    op.drop_column("signals", "causation_id")
    op.drop_column("signals", "correlation_id")
    op.drop_constraint("ck_agent_criticality", "agents", type_="check")
    op.alter_column(
        "agents",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.alter_column(
        "agents",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.drop_column("agents", "supported_evidence_types")
    op.drop_column("agents", "supported_assets")
    op.drop_column("agents", "criticality")
    op.drop_column("agents", "capabilities")
    op.rename_table("used_nonces", "nonces")
