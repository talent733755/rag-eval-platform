"""Add immutable metric definitions and run/sample results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_metrics"
down_revision: str | None = "0011_experiment_run_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def upgrade() -> None:
    op.create_table(
        "metric_definitions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_metric_definitions_project_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            "metric_key",
            "version",
            name="uq_metric_definitions_key_version",
        ),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_metric_definitions_tenant"
        ),
        sa.CheckConstraint("length(trim(metric_key)) > 0", name="metric_definition_key_nonempty"),
        sa.CheckConstraint("length(trim(version)) > 0", name="metric_definition_version_nonempty"),
    )
    op.create_index(
        "ix_metric_definitions_organization_id", "metric_definitions", ["organization_id"]
    )
    op.create_index("ix_metric_definitions_project_id", "metric_definitions", ["project_id"])
    op.create_index(
        "ix_metric_definitions_project_key",
        "metric_definitions",
        ["organization_id", "project_id", "metric_key"],
    )

    op.create_table(
        "metric_results",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experiment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_item_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("metric_definition_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column("metric_version", sa.String(length=50), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("scope_key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("numerator", sa.Float(), nullable=True),
        sa.Column("denominator", sa.Float(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("missing_reason", sa.String(length=255), nullable=True),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("distribution", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["experiment_id", "organization_id", "project_id"],
            ["experiments.id", "experiments.organization_id", "experiments.project_id"],
            name="fk_metric_results_experiment_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "organization_id", "project_id"],
            ["experiment_runs.id", "experiment_runs.organization_id", "experiment_runs.project_id"],
            name="fk_metric_results_run_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_item_id", "organization_id", "project_id"],
            [
                "experiment_run_items.id",
                "experiment_run_items.organization_id",
                "experiment_run_items.project_id",
            ],
            name="fk_metric_results_item_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["metric_definition_id", "organization_id", "project_id"],
            [
                "metric_definitions.id",
                "metric_definitions.organization_id",
                "metric_definitions.project_id",
            ],
            name="fk_metric_results_definition_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "scope_key",
            "metric_definition_id",
            name="uq_metric_results_run_scope_definition",
        ),
        sa.UniqueConstraint("id", "organization_id", "project_id", name="uq_metric_results_tenant"),
        sa.CheckConstraint(
            "(scope = 'run' AND run_item_id IS NULL AND scope_key = 'run') OR "
            "(scope = 'sample' AND run_item_id IS NOT NULL AND scope_key <> 'run')",
            name="metric_result_scope_shape",
        ),
        sa.CheckConstraint("sample_count >= 0", name="metric_result_sample_count_nonnegative"),
    )
    op.create_index("ix_metric_results_organization_id", "metric_results", ["organization_id"])
    op.create_index("ix_metric_results_project_id", "metric_results", ["project_id"])
    op.create_index("ix_metric_results_experiment_id", "metric_results", ["experiment_id"])
    op.create_index("ix_metric_results_run_id", "metric_results", ["run_id"])
    op.create_index(
        "ix_metric_results_run_metric",
        "metric_results",
        ["run_id", "metric_definition_id", "scope"],
    )
    op.create_index("ix_metric_results_item", "metric_results", ["run_item_id"])
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.rag_eval_prevent_metric_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'metric history is append-only'
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    for table in ("metric_definitions", "metric_results"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION public.rag_eval_prevent_metric_mutation();
            """
        )
        op.execute(f"REVOKE UPDATE, DELETE ON TABLE {table} FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS metric_results_append_only ON metric_results")
    op.execute("DROP TRIGGER IF EXISTS metric_definitions_append_only ON metric_definitions")
    op.execute("DROP FUNCTION IF EXISTS public.rag_eval_prevent_metric_mutation()")
    op.drop_index("ix_metric_results_item", table_name="metric_results")
    op.drop_index("ix_metric_results_run_metric", table_name="metric_results")
    op.drop_index("ix_metric_results_run_id", table_name="metric_results")
    op.drop_index("ix_metric_results_experiment_id", table_name="metric_results")
    op.drop_index("ix_metric_results_project_id", table_name="metric_results")
    op.drop_index("ix_metric_results_organization_id", table_name="metric_results")
    op.drop_table("metric_results")
    op.drop_index("ix_metric_definitions_project_key", table_name="metric_definitions")
    op.drop_index("ix_metric_definitions_project_id", table_name="metric_definitions")
    op.drop_index("ix_metric_definitions_organization_id", table_name="metric_definitions")
    op.drop_table("metric_definitions")
