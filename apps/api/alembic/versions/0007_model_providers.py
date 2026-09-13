"""Add secret-free model provider configuration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_model_providers"
down_revision: str | None = "0006_adapters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_provider_configs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("credential_ref", sa.String(length=255), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="30"),
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
            "organization_id", "project_id", "name", name="uq_model_providers_name"
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="model_provider_name_nonempty"),
        sa.CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 300", name="model_provider_timeout_range"
        ),
        sa.CheckConstraint(
            "last_test_status IN ('never', 'succeeded', 'failed')",
            name="model_provider_test_status_check",
        ),
    )
    op.create_index(
        "ix_model_provider_configs_organization_id", "model_provider_configs", ["organization_id"]
    )
    op.create_index(
        "ix_model_provider_configs_project_id", "model_provider_configs", ["project_id"]
    )
    op.create_index(
        "ix_model_providers_project_enabled",
        "model_provider_configs",
        ["organization_id", "project_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_providers_project_enabled", table_name="model_provider_configs")
    op.drop_index("ix_model_provider_configs_project_id", table_name="model_provider_configs")
    op.drop_index("ix_model_provider_configs_organization_id", table_name="model_provider_configs")
    op.drop_table("model_provider_configs")
