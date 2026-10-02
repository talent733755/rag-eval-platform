"""Add the per-item judge verdict column to experiment run items."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_experiment_run_item_judge"
down_revision: str | None = "0016_experiment_usage_aggregates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiment_run_items",
        sa.Column("final_judge", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("experiment_run_items", "final_judge")
