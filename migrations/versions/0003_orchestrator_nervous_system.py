"""Phase 02 durable orchestrator nervous system."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_orchestrator"
down_revision = "0002_architecture_hardening"
branch_labels = None
depends_on = None


RUN_STATES = (
    "CREATED",
    "DISPATCHING",
    "COLLECTING",
    "FULL",
    "DEGRADED",
    "CRITICAL",
    "FAILED",
    "TIMED_OUT",
    "CANCELLED",
)
TASK_STATES = (
    "PENDING",
    "DISPATCHING",
    "ACKNOWLEDGED",
    "WAITING_SIGNAL",
    "SIGNAL_RECEIVED",
    "RETRY",
    "TIMED_OUT",
    "FAILED",
    "CANCELLED",
    "SKIPPED",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "agent_endpoints",
        sa.Column(
            "agent_id",
            sa.String(64),
            sa.ForeignKey("agents.agent_id"),
            primary_key=True,
        ),
        sa.Column("endpoint_url", sa.String(2048), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("transport IN ('HTTP')", name="ck_agent_endpoint_transport"),
        sa.CheckConstraint(
            "environment IN ('TEST','DEVELOPMENT','PRODUCTION')",
            name="ck_agent_endpoint_environment",
        ),
    )
    op.create_table(
        "agent_runtime_states",
        sa.Column(
            "agent_id",
            sa.String(64),
            sa.ForeignKey("agents.agent_id"),
            primary_key=True,
        ),
        sa.Column("availability", sa.String(16), nullable=False),
        sa.Column("last_probe_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_ack_at", sa.DateTime(timezone=True)),
        sa.Column("last_signal_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("circuit_state", sa.String(16), nullable=False),
        sa.Column("circuit_open_until", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "availability IN ('UNKNOWN','HEALTHY','DEGRADED','UNAVAILABLE')",
            name="ck_agent_runtime_availability",
        ),
        sa.CheckConstraint(
            "circuit_state IN ('CLOSED','OPEN','HALF_OPEN')",
            name="ck_agent_runtime_circuit",
        ),
        sa.CheckConstraint("consecutive_failures >= 0", name="ck_agent_runtime_failures"),
    )
    op.create_index("ix_agent_runtime_availability", "agent_runtime_states", ["availability"])
    op.create_table(
        "orchestration_runs",
        sa.Column("orchestration_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market_snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column("asset", sa.String(32), nullable=False),
        sa.Column("trigger_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(24)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("collection_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("trigger_type IN ('MANUAL','TEST')", name="ck_run_trigger"),
        sa.CheckConstraint(
            f"status IN ({_quoted(RUN_STATES)})",
            name="ck_run_status",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('FULL','DEGRADED','CRITICAL','INSUFFICIENT_DATA')",
            name="ck_run_outcome",
        ),
        sa.CheckConstraint("collection_deadline > created_at", name="ck_run_deadline"),
    )
    op.create_index("ix_orchestration_runs_status", "orchestration_runs", ["status"])
    op.create_index("ix_orchestration_runs_snapshot", "orchestration_runs", ["snapshot_id"])
    op.create_table(
        "agent_tasks",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "orchestration_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orchestration_runs.orchestration_run_id"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market_snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(64),
            sa.ForeignKey("agents.agent_id"),
            nullable=False,
        ),
        sa.Column("asset", sa.String(32), nullable=False),
        sa.Column("required_capability", sa.String(64), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("criticality", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("dispatch_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("signal_received_at", sa.DateTime(timezone=True)),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN ({_quoted(TASK_STATES)})", name="ck_agent_task_status"),
        sa.CheckConstraint(
            "criticality IN ('LOW','NORMAL','HIGH','CRITICAL')",
            name="ck_agent_task_criticality",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_agent_task_attempts"),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="ck_agent_task_priority"),
        sa.CheckConstraint(
            "dispatch_deadline > created_at AND signal_deadline >= dispatch_deadline",
            name="ck_agent_task_deadlines",
        ),
        sa.UniqueConstraint(
            "orchestration_run_id",
            "agent_id",
            "asset",
            "required_capability",
            name="uq_agent_task_assignment",
        ),
    )
    op.create_index("ix_agent_tasks_dispatch", "agent_tasks", ["status", "dispatch_after"])
    op.create_index("ix_agent_tasks_run", "agent_tasks", ["orchestration_run_id"])
    op.create_index("ix_agent_tasks_agent", "agent_tasks", ["agent_id"])
    op.create_index("ix_agent_tasks_snapshot", "agent_tasks", ["snapshot_id"])
    op.create_index("ix_agent_tasks_lease", "agent_tasks", ["lease_until"])

    op.add_column("signals", sa.Column("task_id", postgresql.UUID(as_uuid=True)))
    op.add_column("signals", sa.Column("orchestration_run_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key("fk_signals_task", "signals", "agent_tasks", ["task_id"], ["task_id"])
    op.create_foreign_key(
        "fk_signals_orchestration_run",
        "signals",
        "orchestration_runs",
        ["orchestration_run_id"],
        ["orchestration_run_id"],
    )
    op.create_check_constraint(
        "ck_signal_task_lineage",
        "signals",
        "(task_id IS NULL AND orchestration_run_id IS NULL) OR "
        "(task_id IS NOT NULL AND orchestration_run_id IS NOT NULL)",
    )
    op.create_index("uq_signals_task_result", "signals", ["task_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_signals_task_result", table_name="signals")
    op.execute("ALTER TABLE signals DROP CONSTRAINT IF EXISTS ck_signal_task_lineage")
    op.drop_constraint("fk_signals_orchestration_run", "signals", type_="foreignkey")
    op.drop_constraint("fk_signals_task", "signals", type_="foreignkey")
    op.drop_column("signals", "orchestration_run_id")
    op.drop_column("signals", "task_id")
    op.drop_table("agent_tasks")
    op.drop_table("orchestration_runs")
    op.drop_table("agent_runtime_states")
    op.drop_table("agent_endpoints")
