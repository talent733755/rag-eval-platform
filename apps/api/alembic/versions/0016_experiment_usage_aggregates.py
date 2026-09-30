"""Add usage and latency aggregate columns to experiments and runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_experiment_usage_aggregates"
down_revision: str | None = "0015_schema_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES: tuple[str, ...] = ("experiments", "experiment_runs")
_TOKEN_COLUMNS: tuple[str, ...] = ("total_input_tokens", "total_output_tokens", "total_tokens")


def upgrade() -> None:
    for table in _TABLES:
        for column in _TOKEN_COLUMNS:
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
        op.add_column(
            table,
            sa.Column("total_latency_ms", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "total_latency_ms")
        for column in reversed(_TOKEN_COLUMNS):
            op.drop_column(table, column)
