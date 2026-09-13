"""Add explicit source and configuration references to generation jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_candidate_generation_jobs"
down_revision: str | None = "0004_candidate_dataset_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_candidate_dataset_versions_dataset_tenant",
        "candidate_dataset_versions",
        ["id", "dataset_id", "organization_id", "project_id"],
    )
    op.drop_constraint(
        "ck_ingestion_jobs_job_resource_matches_kind", "ingestion_jobs", type_="check"
    )
    op.add_column(
        "ingestion_jobs", sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=True)
    )
    op.add_column(
        "ingestion_jobs", sa.Column("generation_config_id", sa.Uuid(as_uuid=True), nullable=True)
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("candidate_dataset_version_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index("ix_ingestion_jobs_source_version_id", "ingestion_jobs", ["source_version_id"])
    op.create_index(
        "ix_ingestion_jobs_generation_config_id", "ingestion_jobs", ["generation_config_id"]
    )
    op.create_index(
        "ix_ingestion_jobs_candidate_dataset_version_id",
        "ingestion_jobs",
        ["candidate_dataset_version_id"],
    )
    op.create_foreign_key(
        "fk_ingestion_jobs_source_version_tenant",
        "ingestion_jobs",
        "document_versions",
        ["source_version_id", "organization_id", "project_id"],
        ["id", "organization_id", "project_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_ingestion_jobs_candidate_dataset_version_tenant",
        "ingestion_jobs",
        "candidate_dataset_versions",
        ["candidate_dataset_version_id", "candidate_dataset_id", "organization_id", "project_id"],
        ["id", "dataset_id", "organization_id", "project_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_ingestion_jobs_generation_config_dataset_tenant",
        "ingestion_jobs",
        "candidate_generation_configs",
        ["generation_config_id", "candidate_dataset_id", "organization_id", "project_id"],
        ["id", "dataset_id", "organization_id", "project_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_ingestion_jobs_job_resource_matches_kind",
        "ingestion_jobs",
        "((job_kind = 'parse' AND document_version_id IS NOT NULL AND candidate_dataset_id IS NULL AND source_version_id IS NULL AND generation_config_id IS NULL AND candidate_dataset_version_id IS NULL) OR (job_kind = 'generate_candidates' AND document_version_id IS NULL AND candidate_dataset_id IS NOT NULL AND source_version_id IS NOT NULL AND generation_config_id IS NOT NULL AND candidate_dataset_version_id IS NOT NULL))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ingestion_jobs_job_resource_matches_kind", "ingestion_jobs", type_="check"
    )
    op.drop_constraint(
        "fk_ingestion_jobs_candidate_dataset_version_tenant", "ingestion_jobs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_ingestion_jobs_generation_config_dataset_tenant", "ingestion_jobs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_ingestion_jobs_source_version_tenant", "ingestion_jobs", type_="foreignkey"
    )
    op.drop_index("ix_ingestion_jobs_generation_config_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_candidate_dataset_version_id", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_source_version_id", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "generation_config_id")
    op.drop_column("ingestion_jobs", "candidate_dataset_version_id")
    op.drop_column("ingestion_jobs", "source_version_id")
    op.create_check_constraint(
        "ck_ingestion_jobs_job_resource_matches_kind",
        "ingestion_jobs",
        "((job_kind = 'parse' AND document_version_id IS NOT NULL AND candidate_dataset_id IS NULL) OR (job_kind = 'generate_candidates' AND document_version_id IS NULL AND candidate_dataset_id IS NOT NULL))",
    )
    op.drop_constraint(
        "uq_candidate_dataset_versions_dataset_tenant",
        "candidate_dataset_versions",
        type_="unique",
    )
