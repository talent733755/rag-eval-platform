"""Harden ingestion final status, candidate config provenance, and immutability."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_ingestion_hardening"
down_revision: str | None = "0002_document_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing 0002 installations used VARCHAR(9), which made the invalid
    # runtime value ``processing`` fail with a length error before the final
    # status CHECK could reject it. Ten characters matches the job status
    # envelope while the CHECK remains terminal-only.
    op.execute(
        "ALTER TABLE ingestion_job_attempts "
        "ALTER COLUMN final_status TYPE VARCHAR(10)"
    )

    op.create_unique_constraint(
        "uq_candidate_generation_configs_dataset_tenant_identity",
        "candidate_generation_configs",
        ["id", "dataset_id", "organization_id", "project_id"],
    )
    op.drop_constraint(
        "fk_candidate_dataset_items_generation_config_tenant",
        "candidate_dataset_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_candidate_dataset_items_generation_config_dataset_tenant",
        "candidate_dataset_items",
        "candidate_generation_configs",
        ["generation_config_id", "dataset_id", "organization_id", "project_id"],
        ["id", "dataset_id", "organization_id", "project_id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger
                WHERE tgname = 'candidate_generation_configs_truncate_guard'
                  AND tgrelid = 'candidate_generation_configs'::regclass
            ) THEN
                CREATE TRIGGER candidate_generation_configs_truncate_guard
                BEFORE TRUNCATE ON candidate_generation_configs
                FOR EACH STATEMENT
                EXECUTE FUNCTION public.rag_eval_prevent_generation_config_mutation();
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS candidate_generation_configs_truncate_guard "
        "ON candidate_generation_configs"
    )
    op.drop_constraint(
        "fk_candidate_dataset_items_generation_config_dataset_tenant",
        "candidate_dataset_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_candidate_dataset_items_generation_config_tenant",
        "candidate_dataset_items",
        "candidate_generation_configs",
        ["generation_config_id", "organization_id", "project_id"],
        ["id", "organization_id", "project_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_candidate_generation_configs_dataset_tenant_identity",
        "candidate_generation_configs",
        type_="unique",
    )
    op.execute(
        "ALTER TABLE ingestion_job_attempts "
        "ALTER COLUMN final_status TYPE VARCHAR(9)"
    )
