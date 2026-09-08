"""Phase 03 additive analytical lineage for pilot role signals."""

import sqlalchemy as sa
from alembic import op

revision = "0004_pilot_agents"
down_revision = "0003_orchestrator"
branch_labels = None
depends_on = None

_LINEAGE_COLUMNS = (
    "role_id",
    "role_version",
    "config_version",
    "feature_pipeline_version",
    "analysis_schema_version",
    "data_provider",
    "data_as_of",
    "confidence_model_version",
)


def upgrade() -> None:
    op.add_column("signals", sa.Column("role_id", sa.String(64)))
    op.add_column("signals", sa.Column("role_version", sa.String(32)))
    op.add_column("signals", sa.Column("config_version", sa.String(32)))
    op.add_column("signals", sa.Column("feature_pipeline_version", sa.String(64)))
    op.add_column("signals", sa.Column("analysis_schema_version", sa.String(16)))
    op.add_column("signals", sa.Column("data_provider", sa.String(128)))
    op.add_column("signals", sa.Column("data_as_of", sa.DateTime(timezone=True)))
    op.add_column("signals", sa.Column("confidence_model_version", sa.String(32)))
    op.create_check_constraint(
        "ck_signal_analytical_lineage",
        "signals",
        "(role_id IS NULL AND role_version IS NULL AND config_version IS NULL AND "
        "feature_pipeline_version IS NULL AND analysis_schema_version IS NULL AND "
        "data_provider IS NULL AND data_as_of IS NULL AND confidence_model_version IS NULL) "
        "OR (role_id IS NOT NULL AND role_version IS NOT NULL AND config_version IS NOT NULL "
        "AND feature_pipeline_version IS NOT NULL AND analysis_schema_version IS NOT NULL "
        "AND data_provider IS NOT NULL AND data_as_of IS NOT NULL "
        "AND confidence_model_version IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_signal_data_cutoff",
        "signals",
        "data_as_of IS NULL OR data_as_of <= analysis_timestamp",
    )
    op.create_index(
        "ix_signals_role_version",
        "signals",
        ["role_id", "role_version", "config_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_signals_role_version", table_name="signals")
    op.drop_constraint("ck_signal_data_cutoff", "signals", type_="check")
    op.drop_constraint("ck_signal_analytical_lineage", "signals", type_="check")
    for column in reversed(_LINEAGE_COLUMNS):
        op.drop_column("signals", column)
