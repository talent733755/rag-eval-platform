"""Add tenant-scoped adapter configuration without credential material."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_adapters"
down_revision: str | None = "0005_candidate_generation_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "adapter_configs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=7), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=True),
        sa.Column("credential_ref", sa.String(length=255), nullable=True),
        sa.Column("token_last4", sa.String(length=4), nullable=True),
        sa.Column("adapter_version", sa.String(length=100), nullable=False),
        sa.Column("trace_level", sa.String(length=20), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="30"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_test_status", sa.String(length=9), nullable=False, server_default="never"),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "project_id", "name", name="uq_adapter_configs_name"
        ),
        sa.CheckConstraint("kind IN ('http', 'python')", name="adapter_kind_check"),
        sa.CheckConstraint("length(trim(name)) > 0", name="adapter_name_nonempty"),
        sa.CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 300", name="adapter_timeout_range"
        ),
        sa.CheckConstraint("retry_count >= 0 AND retry_count <= 5", name="adapter_retry_range"),
        sa.CheckConstraint(
            "last_test_status IN ('never', 'succeeded', 'failed')", name="adapter_test_status_check"
        ),
    )
    op.create_index("ix_adapter_configs_organization_id", "adapter_configs", ["organization_id"])
    op.create_index("ix_adapter_configs_project_id", "adapter_configs", ["project_id"])
    op.create_index(
        "ix_adapter_configs_project_enabled",
        "adapter_configs",
        ["organization_id", "project_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_adapter_configs_project_enabled", table_name="adapter_configs")
    op.drop_index("ix_adapter_configs_project_id", table_name="adapter_configs")
    op.drop_index("ix_adapter_configs_organization_id", table_name="adapter_configs")
    op.drop_table("adapter_configs")
