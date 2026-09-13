"""Add immutable experiment and recoverable run records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_experiments"
down_revision: str | None = "0008_adapter_entrypoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_model_provider_configs_tenant",
        "model_provider_configs",
        ["id", "organization_id", "project_id"],
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="draft"),
        sa.Column("dataset_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("adapter_config_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("model_provider_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("metric_versions", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("configuration_snapshot", sa.JSON(), nullable=False),
        sa.Column("environment_hash", sa.String(length=64), nullable=False),
        sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id", "organization_id"], ["projects.id", "projects.organization_id"], name="fk_experiments_project_organization_projects", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_version_id", "organization_id", "project_id"], ["candidate_dataset_versions.id", "candidate_dataset_versions.organization_id", "candidate_dataset_versions.project_id"], name="fk_experiments_dataset_version_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["adapter_config_id", "organization_id", "project_id"], ["adapter_configs.id", "adapter_configs.organization_id", "adapter_configs.project_id"], name="fk_experiments_adapter_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_provider_id", "organization_id", "project_id"], ["model_provider_configs.id", "model_provider_configs.organization_id", "model_provider_configs.project_id"], name="fk_experiments_provider_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", "project_id", name="uq_experiments_tenant"),
        sa.CheckConstraint("length(trim(name)) > 0", name="experiment_name_nonempty"),
        sa.CheckConstraint("total_units >= 0 AND completed_units >= 0", name="experiment_units_nonnegative"),
        sa.CheckConstraint("succeeded_units >= 0 AND failed_units >= 0 AND skipped_units >= 0", name="experiment_results_nonnegative"),
    )
    op.create_index("ix_experiments_organization_id", "experiments", ["organization_id"])
    op.create_index("ix_experiments_project_id", "experiments", ["project_id"])
    op.create_index("ix_experiments_project_status_created", "experiments", ["organization_id", "project_id", "status", "created_at"])

    op.create_table(
        "experiment_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experiment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="queued"),
        sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id", "organization_id"], ["projects.id", "projects.organization_id"], name="fk_experiment_runs_project_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["experiment_id", "organization_id", "project_id"], ["experiments.id", "experiments.organization_id", "experiments.project_id"], name="fk_experiment_runs_experiment_tenant", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", "project_id", name="uq_experiment_runs_tenant"),
    )
    op.create_index("ix_experiment_runs_organization_id", "experiment_runs", ["organization_id"])
    op.create_index("ix_experiment_runs_project_id", "experiment_runs", ["project_id"])
    op.create_index("ix_experiment_runs_project_status_created", "experiment_runs", ["organization_id", "project_id", "status", "created_at"])

    op.create_table(
        "experiment_run_items",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("candidate_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("final_usage", sa.JSON(), nullable=True),
        sa.Column("final_latency_ms", sa.Integer(), nullable=True),
        sa.Column("final_trace_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id", "organization_id", "project_id"], ["experiment_runs.id", "experiment_runs.organization_id", "experiment_runs.project_id"], name="fk_experiment_run_items_run_tenant", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_item_id", "organization_id", "project_id"], ["candidate_dataset_items.id", "candidate_dataset_items.organization_id", "candidate_dataset_items.project_id"], name="fk_experiment_run_items_candidate_tenant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", "project_id", name="uq_experiment_run_items_tenant"),
        sa.UniqueConstraint("run_id", "candidate_item_id", name="uq_experiment_run_items_candidate"),
    )
    op.create_index("ix_experiment_run_items_organization_id", "experiment_run_items", ["organization_id"])
    op.create_index("ix_experiment_run_items_project_id", "experiment_run_items", ["project_id"])
    op.create_index("ix_experiment_run_items_run_status", "experiment_run_items", ["run_id", "status"])

    op.create_table(
        "experiment_run_attempts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["run_item_id", "organization_id", "project_id"], ["experiment_run_items.id", "experiment_run_items.organization_id", "experiment_run_items.project_id"], name="fk_experiment_run_attempts_item_tenant", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_item_id", "attempt_number", name="uq_experiment_run_attempt_number"),
    )
    op.create_index("ix_experiment_run_attempts_organization_id", "experiment_run_attempts", ["organization_id"])
    op.create_index("ix_experiment_run_attempts_project_id", "experiment_run_attempts", ["project_id"])
    op.create_index("ix_experiment_run_attempts_item_created", "experiment_run_attempts", ["run_item_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_experiment_run_attempts_item_created", table_name="experiment_run_attempts")
    op.drop_index("ix_experiment_run_attempts_project_id", table_name="experiment_run_attempts")
    op.drop_index("ix_experiment_run_attempts_organization_id", table_name="experiment_run_attempts")
    op.drop_table("experiment_run_attempts")
    op.drop_index("ix_experiment_run_items_run_status", table_name="experiment_run_items")
    op.drop_index("ix_experiment_run_items_project_id", table_name="experiment_run_items")
    op.drop_index("ix_experiment_run_items_organization_id", table_name="experiment_run_items")
    op.drop_table("experiment_run_items")
    op.drop_index("ix_experiment_runs_project_status_created", table_name="experiment_runs")
    op.drop_index("ix_experiment_runs_project_id", table_name="experiment_runs")
    op.drop_index("ix_experiment_runs_organization_id", table_name="experiment_runs")
    op.drop_table("experiment_runs")
    op.drop_index("ix_experiments_project_status_created", table_name="experiments")
    op.drop_index("ix_experiments_project_id", table_name="experiments")
    op.drop_index("ix_experiments_organization_id", table_name="experiments")
    op.drop_table("experiments")
    op.drop_constraint("uq_model_provider_configs_tenant", "model_provider_configs", type_="unique")
