"""Allow adapter configurations to select trusted installed Python entry points."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_adapter_entrypoints"
down_revision: str | None = "0007_model_providers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("adapter_configs", sa.Column("entrypoint_ref", sa.String(length=255), nullable=True))
    op.create_unique_constraint(
        "uq_adapter_configs_tenant", "adapter_configs", ["id", "organization_id", "project_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_adapter_configs_tenant", "adapter_configs", type_="unique")
    op.drop_column("adapter_configs", "entrypoint_ref")
