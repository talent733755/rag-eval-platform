"""Align legacy tables with the current ORM contract."""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_schema_alignment"
down_revision: str | None = "0014_regression_cases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_experiments_dataset_version_id", "experiments", ("dataset_version_id",)),
    ("ix_experiments_adapter_config_id", "experiments", ("adapter_config_id",)),
    ("ix_experiments_model_provider_id", "experiments", ("model_provider_id",)),
    ("ix_experiment_runs_experiment_id", "experiment_runs", ("experiment_id",)),
    ("ix_experiment_run_items_run_id", "experiment_run_items", ("run_id",)),
    (
        "ix_experiment_run_items_candidate_item_id",
        "experiment_run_items",
        ("candidate_item_id",),
    ),
    ("ix_experiment_run_attempts_run_item_id", "experiment_run_attempts", ("run_item_id",)),
    ("ix_metric_results_run_item_id", "metric_results", ("run_item_id",)),
    (
        "ix_metric_results_metric_definition_id",
        "metric_results",
        ("metric_definition_id",),
    ),
    ("ix_traces_run_item_id", "traces", ("run_item_id",)),
    ("ix_failure_cases_run_item_id", "failure_cases", ("run_item_id",)),
)


def upgrade() -> None:
    op.drop_index("ix_failure_cases_run_item", table_name="failure_cases")
    for index_name, table_name, columns in _INDEXES:
        op.create_index(index_name, table_name, columns)
    op.create_foreign_key(
        "fk_experiment_run_attempts_organization_id_organizations",
        "experiment_run_attempts",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_experiment_run_attempts_organization_id_organizations",
        "experiment_run_attempts",
        type_="foreignkey",
    )
    for index_name, table_name, _columns in reversed(_INDEXES):
        op.drop_index(index_name, table_name=table_name)
    op.create_index("ix_failure_cases_run_item", "failure_cases", ["run_item_id"])
