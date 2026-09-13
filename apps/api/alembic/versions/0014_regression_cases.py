"""Add immutable regression cases retaining failure lineage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_regression_cases"
down_revision: str | None = "0013_traces_failures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "regression_cases",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("failure_case_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("candidate_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("trace_record_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_regression_cases_project_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["failure_case_id", "organization_id", "project_id"],
            ["failure_cases.id", "failure_cases.organization_id", "failure_cases.project_id"],
            name="fk_regression_cases_failure_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_item_id", "organization_id", "project_id"],
            [
                "experiment_run_items.id",
                "experiment_run_items.organization_id",
                "experiment_run_items.project_id",
            ],
            name="fk_regression_cases_item_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_item_id", "organization_id", "project_id"],
            [
                "candidate_dataset_items.id",
                "candidate_dataset_items.organization_id",
                "candidate_dataset_items.project_id",
            ],
            name="fk_regression_cases_candidate_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id", "organization_id", "project_id"],
            [
                "candidate_dataset_versions.id",
                "candidate_dataset_versions.organization_id",
                "candidate_dataset_versions.project_id",
            ],
            name="fk_regression_cases_dataset_version_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trace_record_id", "organization_id", "project_id"],
            ["traces.id", "traces.organization_id", "traces.project_id"],
            name="fk_regression_cases_trace_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "project_id", "failure_case_id", name="uq_regression_cases_failure"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            "idempotency_key",
            name="uq_regression_cases_idempotency",
        ),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_regression_cases_tenant"
        ),
    )
    op.create_index("ix_regression_cases_organization_id", "regression_cases", ["organization_id"])
    op.create_index("ix_regression_cases_project_id", "regression_cases", ["project_id"])
    op.create_index("ix_regression_cases_failure_case_id", "regression_cases", ["failure_case_id"])
    op.create_index("ix_regression_cases_run_item_id", "regression_cases", ["run_item_id"])
    op.create_index(
        "ix_regression_cases_candidate_item_id", "regression_cases", ["candidate_item_id"]
    )
    op.create_index(
        "ix_regression_cases_dataset_version_id", "regression_cases", ["dataset_version_id"]
    )
    op.create_index("ix_regression_cases_trace_record_id", "regression_cases", ["trace_record_id"])
    op.create_index(
        "ix_regression_cases_project_status",
        "regression_cases",
        ["organization_id", "project_id", "status"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.rag_eval_prevent_regression_case_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'regression cases are append-only'
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        CREATE TRIGGER regression_cases_append_only
        BEFORE UPDATE OR DELETE ON regression_cases
        FOR EACH ROW
        EXECUTE FUNCTION public.rag_eval_prevent_regression_case_mutation();
        REVOKE UPDATE, DELETE ON TABLE regression_cases FROM PUBLIC;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS regression_cases_append_only ON regression_cases")
    op.execute("DROP FUNCTION IF EXISTS public.rag_eval_prevent_regression_case_mutation()")
    for index in (
        "ix_regression_cases_project_status",
        "ix_regression_cases_trace_record_id",
        "ix_regression_cases_dataset_version_id",
        "ix_regression_cases_candidate_item_id",
        "ix_regression_cases_run_item_id",
        "ix_regression_cases_failure_case_id",
        "ix_regression_cases_project_id",
        "ix_regression_cases_organization_id",
    ):
        op.drop_index(index, table_name="regression_cases")
    op.drop_table("regression_cases")
