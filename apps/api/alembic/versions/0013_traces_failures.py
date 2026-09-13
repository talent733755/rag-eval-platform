"""Add immutable Trace and failure diagnosis history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_traces_failures"
down_revision: str | None = "0012_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _tenant_fk(table: str, *, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["experiment_id", "organization_id", "project_id"],
        ["experiments.id", "experiments.organization_id", "experiments.project_id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "traces",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experiment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("trace_version", sa.String(length=50), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        _tenant_fk("traces", name="fk_traces_experiment_tenant"),
        sa.ForeignKeyConstraint(
            ["run_id", "organization_id", "project_id"],
            ["experiment_runs.id", "experiment_runs.organization_id", "experiment_runs.project_id"],
            name="fk_traces_run_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_item_id", "organization_id", "project_id"],
            [
                "experiment_run_items.id",
                "experiment_run_items.organization_id",
                "experiment_run_items.project_id",
            ],
            name="fk_traces_item_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_item_id", "trace_id", name="uq_traces_run_item_trace"),
        sa.UniqueConstraint("id", "organization_id", "project_id", name="uq_traces_tenant"),
    )
    op.create_index("ix_traces_organization_id", "traces", ["organization_id"])
    op.create_index("ix_traces_project_id", "traces", ["project_id"])
    op.create_index("ix_traces_experiment_id", "traces", ["experiment_id"])
    op.create_index("ix_traces_run_id", "traces", ["run_id"])
    op.create_index("ix_traces_run_item", "traces", ["run_item_id"])
    op.create_index(
        "ix_traces_project_created", "traces", ["organization_id", "project_id", "created_at"]
    )

    op.create_table(
        "failure_cases",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experiment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("safe_message", sa.String(length=500), nullable=False),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        _tenant_fk("failure_cases", name="fk_failure_cases_experiment_tenant"),
        sa.ForeignKeyConstraint(
            ["run_id", "organization_id", "project_id"],
            ["experiment_runs.id", "experiment_runs.organization_id", "experiment_runs.project_id"],
            name="fk_failure_cases_run_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_item_id", "organization_id", "project_id"],
            [
                "experiment_run_items.id",
                "experiment_run_items.organization_id",
                "experiment_run_items.project_id",
            ],
            name="fk_failure_cases_item_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_item_id", "attempt_number", name="uq_failure_cases_item_attempt"),
        sa.UniqueConstraint("id", "organization_id", "project_id", name="uq_failure_cases_tenant"),
    )
    op.create_index("ix_failure_cases_organization_id", "failure_cases", ["organization_id"])
    op.create_index("ix_failure_cases_project_id", "failure_cases", ["project_id"])
    op.create_index("ix_failure_cases_experiment_id", "failure_cases", ["experiment_id"])
    op.create_index("ix_failure_cases_run_id", "failure_cases", ["run_id"])
    op.create_index("ix_failure_cases_run_item", "failure_cases", ["run_item_id"])
    op.create_index(
        "ix_failure_cases_project_created",
        "failure_cases",
        ["organization_id", "project_id", "created_at"],
    )
    op.create_index("ix_failure_cases_run_code", "failure_cases", ["run_id", "code"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.rag_eval_prevent_trace_failure_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'trace and failure history is append-only'
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    for table in ("traces", "failure_cases"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION public.rag_eval_prevent_trace_failure_mutation();
            """
        )
        op.execute(f"REVOKE UPDATE, DELETE ON TABLE {table} FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS failure_cases_append_only ON failure_cases")
    op.execute("DROP TRIGGER IF EXISTS traces_append_only ON traces")
    op.execute("DROP FUNCTION IF EXISTS public.rag_eval_prevent_trace_failure_mutation()")
    for index in (
        "ix_failure_cases_run_code",
        "ix_failure_cases_project_created",
        "ix_failure_cases_run_item",
        "ix_failure_cases_run_id",
        "ix_failure_cases_experiment_id",
        "ix_failure_cases_project_id",
        "ix_failure_cases_organization_id",
    ):
        op.drop_index(index, table_name="failure_cases")
    op.drop_table("failure_cases")
    for index in (
        "ix_traces_project_created",
        "ix_traces_run_item",
        "ix_traces_run_id",
        "ix_traces_experiment_id",
        "ix_traces_project_id",
        "ix_traces_organization_id",
    ):
        op.drop_index(index, table_name="traces")
    op.drop_table("traces")
