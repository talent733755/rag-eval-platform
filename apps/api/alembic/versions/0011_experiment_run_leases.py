"""Add lease and fencing fields to experiment runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_experiment_run_leases"
down_revision: str | None = "0010_experiment_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("experiment_runs", sa.Column("worker_id", sa.String(length=255), nullable=True))
    op.add_column(
        "experiment_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "experiment_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "experiment_runs",
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("experiment_runs", "fencing_token")
    op.drop_column("experiment_runs", "heartbeat_at")
    op.drop_column("experiment_runs", "lease_expires_at")
    op.drop_column("experiment_runs", "worker_id")
