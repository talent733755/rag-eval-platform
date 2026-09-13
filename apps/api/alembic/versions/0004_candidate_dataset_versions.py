"""Add immutable candidate dataset versions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql.elements import conv

revision: str = "0004_candidate_dataset_versions"
down_revision: str | None = "0003_ingestion_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_dataset_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_snapshot_hash", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "version_number > 0", name=conv("ck_candidate_dataset_versions_version_number_positive")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name=conv("ck_candidate_dataset_versions_valid_status"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dataset_id", "organization_id", "project_id"],
            [
                "candidate_datasets.id",
                "candidate_datasets.organization_id",
                "candidate_datasets.project_id",
            ],
            name="fk_candidate_dataset_versions_dataset_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_dataset_versions"),
        sa.UniqueConstraint(
            "dataset_id", "version_number", name="uq_candidate_dataset_versions_number"
        ),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_candidate_dataset_versions_tenant"
        ),
    )
    for column in ("organization_id", "project_id", "dataset_id"):
        op.create_index(
            f"ix_candidate_dataset_versions_{column}", "candidate_dataset_versions", [column]
        )
    op.create_index(
        "ix_candidate_dataset_versions_project_status",
        "candidate_dataset_versions",
        ["organization_id", "project_id", "status"],
    )
    op.add_column(
        "candidate_dataset_items",
        sa.Column("dataset_version_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_candidate_dataset_items_dataset_version_id",
        "candidate_dataset_items",
        ["dataset_version_id"],
    )
    op.create_foreign_key(
        "fk_candidate_dataset_items_dataset_version_tenant",
        "candidate_dataset_items",
        "candidate_dataset_versions",
        ["dataset_version_id", "organization_id", "project_id"],
        ["id", "organization_id", "project_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_candidate_dataset_items_dataset_version_tenant",
        "candidate_dataset_items",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_candidate_dataset_items_dataset_version_id", table_name="candidate_dataset_items"
    )
    op.drop_column("candidate_dataset_items", "dataset_version_id")
    op.drop_index(
        "ix_candidate_dataset_versions_project_status", table_name="candidate_dataset_versions"
    )
    for column in ("organization_id", "project_id", "dataset_id"):
        op.drop_index(
            f"ix_candidate_dataset_versions_{column}", table_name="candidate_dataset_versions"
        )
    op.drop_table("candidate_dataset_versions")
