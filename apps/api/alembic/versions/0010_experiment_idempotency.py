"""Add idempotency keys to experiment drafts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_experiment_idempotency"
down_revision: str | None = "0009_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.execute("UPDATE experiments SET idempotency_key = CAST(id AS VARCHAR(255))")
    op.alter_column("experiments", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_experiments_idempotency", "experiments", ["organization_id", "project_id", "idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_experiments_idempotency", "experiments", type_="unique")
    op.drop_column("experiments", "idempotency_key")
