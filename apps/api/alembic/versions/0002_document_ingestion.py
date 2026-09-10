"""Add tenant-scoped document ingestion and candidate provenance tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql.elements import conv

revision: str = "0002_document_ingestion"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _utc_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.text("CURRENT_TIMESTAMP") if not nullable else None,
    )


def upgrade() -> None:
    # documents is intentionally created without latest_version_id's FK. The referenced
    # document_versions table does not exist yet; the FK is added after all tables exist.
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=8), nullable=False),
        sa.Column("latest_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _utc_column("created_at"),
        _utc_column("updated_at"),
        sa.CheckConstraint(
            "length(trim(display_name)) > 0", name=conv("ck_documents_display_name_nonempty")
        ),
        sa.CheckConstraint(
            "source_type IN ('pdf', 'docx', 'markdown', 'txt')",
            name=conv("ck_documents_document_source_type"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_documents_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_documents_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_documents_tenant_identity"
        ),
    )
    op.create_index("ix_documents_organization_id", "documents", ["organization_id"])
    op.create_index("ix_documents_project_id", "documents", ["project_id"])
    op.create_index(
        "ix_documents_project_updated_at",
        "documents",
        ["organization_id", "project_id", "updated_at"],
    )

    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("detected_mime", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=True),
        sa.Column("parse_status", sa.String(length=10), nullable=False),
        sa.Column("parse_error_code", sa.String(length=100), nullable=True),
        sa.Column("parse_error_message", sa.Text(), nullable=True),
        sa.Column("parsed_character_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        _utc_column("created_at"),
        _utc_column("updated_at"),
        sa.CheckConstraint(
            "version_number > 0", name=conv("ck_document_versions_version_number_positive")
        ),
        sa.CheckConstraint("byte_size > 0", name=conv("ck_document_versions_byte_size_positive")),
        sa.CheckConstraint(
            "parse_status IN ('queued', 'processing', 'succeeded', 'failed', 'cancelled')",
            name=conv("ck_document_versions_document_parse_status"),
        ),
        sa.CheckConstraint(
            "parsed_character_count >= 0",
            name=conv("ck_document_versions_parsed_character_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "page_count >= 0", name=conv("ck_document_versions_page_count_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_document_versions_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "organization_id", "project_id"],
            ["documents.id", "documents.organization_id", "documents.project_id"],
            name="fk_document_versions_document_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_document_versions_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_document_versions_tenant_identity"
        ),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_version_number"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            "sha256",
            "byte_size",
            name="uq_document_versions_project_content_identity",
        ),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name=conv("ck_document_versions_sha256_lower_hex_64")
        ),
    )
    op.create_index(
        "ix_document_versions_organization_id", "document_versions", ["organization_id"]
    )
    op.create_index("ix_document_versions_project_id", "document_versions", ["project_id"])
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index(
        "ix_document_versions_project_status",
        "document_versions",
        ["organization_id", "project_id", "parse_status"],
    )
    op.create_index(
        "ix_document_versions_document_created_at",
        "document_versions",
        ["document_id", "created_at"],
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("paragraph_index", sa.Integer(), nullable=True),
        sa.Column("source_location", sa.JSON(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name=conv("ck_document_chunks_ordinal_nonnegative")),
        sa.CheckConstraint(
            "character_count >= 0", name=conv("ck_document_chunks_character_count_nonnegative")
        ),
        sa.CheckConstraint(
            "token_count >= 0", name=conv("ck_document_chunks_token_count_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_document_chunks_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_document_chunks_version_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_document_chunks_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_document_chunks_tenant_identity"
        ),
        sa.UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_chunks_version_ordinal"
        ),
        sa.UniqueConstraint(
            "id",
            "document_version_id",
            "organization_id",
            "project_id",
            name="uq_document_chunks_version_tenant_identity",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name=conv("ck_document_chunks_content_hash_lower_hex_64"),
        ),
    )
    for column in ("organization_id", "project_id", "document_version_id"):
        op.create_index(f"ix_document_chunks_{column}", "document_chunks", [column])
    op.create_index(
        "ix_document_chunks_project_version",
        "document_chunks",
        ["organization_id", "project_id", "document_version_id"],
    )

    op.create_table(
        "candidate_datasets",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        _utc_column("created_at"),
        _utc_column("updated_at"),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name=conv("ck_candidate_datasets_name_nonempty")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name=conv("ck_candidate_datasets_candidate_dataset_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_candidate_datasets_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_candidate_datasets_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_datasets"),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_candidate_datasets_tenant_identity"
        ),
    )
    op.create_index(
        "ix_candidate_datasets_organization_id", "candidate_datasets", ["organization_id"]
    )
    op.create_index("ix_candidate_datasets_project_id", "candidate_datasets", ["project_id"])
    op.create_index(
        "ix_candidate_datasets_project_status",
        "candidate_datasets",
        ["organization_id", "project_id", "status"],
    )

    op.create_table(
        "candidate_generation_configs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("capability_version", sa.String(length=100), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=True),
        sa.Column("normalizer_version", sa.String(length=100), nullable=True),
        sa.Column("check_rules_version", sa.String(length=100), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("randomness", sa.Float(), nullable=False, server_default="0"),
        sa.Column("requested_version_ids", sa.JSON(), nullable=False),
        sa.Column("chunk_content_hashes", sa.JSON(), nullable=False),
        sa.Column("environment", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("actual_cost", sa.Float(), nullable=False, server_default="0"),
        _utc_column("created_at"),
        sa.CheckConstraint(
            "length(trim(capability_version)) > 0",
            name=conv("ck_candidate_generation_configs_capability_version_nonempty"),
        ),
        sa.CheckConstraint(
            "randomness >= 0", name=conv("ck_candidate_generation_configs_randomness_nonnegative")
        ),
        sa.CheckConstraint(
            "estimated_cost >= 0",
            name=conv("ck_candidate_generation_configs_estimated_cost_nonnegative"),
        ),
        sa.CheckConstraint(
            "actual_cost >= 0", name=conv("ck_candidate_generation_configs_actual_cost_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_candidate_generation_configs_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "organization_id", "project_id"],
            [
                "candidate_datasets.id",
                "candidate_datasets.organization_id",
                "candidate_datasets.project_id",
            ],
            name="fk_candidate_generation_configs_dataset_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_candidate_generation_configs_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_generation_configs"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            "project_id",
            name="uq_candidate_generation_configs_tenant_identity",
        ),
    )
    for column in ("organization_id", "project_id", "dataset_id"):
        op.create_index(
            f"ix_candidate_generation_configs_{column}", "candidate_generation_configs", [column]
        )
    op.create_index(
        "ix_candidate_generation_configs_dataset_created_at",
        "candidate_generation_configs",
        ["dataset_id", "created_at"],
    )

    op.create_table(
        "candidate_dataset_items",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("generation_config_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(length=100), nullable=False),
        sa.Column("difficulty", sa.String(length=100), nullable=True),
        sa.Column("reference_answer", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("automatic_checks", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(length=8), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        _utc_column("created_at"),
        _utc_column("updated_at"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=conv("ck_candidate_dataset_items_confidence_range"),
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name=conv("ck_candidate_dataset_items_candidate_review_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_candidate_dataset_items_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "organization_id", "project_id"],
            [
                "candidate_datasets.id",
                "candidate_datasets.organization_id",
                "candidate_datasets.project_id",
            ],
            name="fk_candidate_dataset_items_dataset_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_candidate_dataset_items_source_version_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generation_config_id", "organization_id", "project_id"],
            [
                "candidate_generation_configs.id",
                "candidate_generation_configs.organization_id",
                "candidate_generation_configs.project_id",
            ],
            name="fk_candidate_dataset_items_generation_config_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_candidate_dataset_items_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_dataset_items"),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_candidate_dataset_items_tenant_identity"
        ),
        sa.UniqueConstraint(
            "id",
            "source_version_id",
            "organization_id",
            "project_id",
            name="uq_candidate_dataset_items_source_version_tenant_identity",
        ),
    )
    for column in (
        "organization_id",
        "project_id",
        "dataset_id",
        "generation_config_id",
        "source_version_id",
    ):
        op.create_index(f"ix_candidate_dataset_items_{column}", "candidate_dataset_items", [column])
    op.create_index(
        "ix_candidate_dataset_items_dataset_review",
        "candidate_dataset_items",
        ["dataset_id", "review_status"],
    )

    op.create_table(
        "candidate_item_evidence",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("item_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "ordinal >= 0", name=conv("ck_candidate_item_evidence_ordinal_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_candidate_item_evidence_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id", "source_version_id", "organization_id", "project_id"],
            [
                "candidate_dataset_items.id",
                "candidate_dataset_items.source_version_id",
                "candidate_dataset_items.organization_id",
                "candidate_dataset_items.project_id",
            ],
            name="fk_candidate_item_evidence_item_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_candidate_item_evidence_source_version_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id", "source_version_id", "organization_id", "project_id"],
            [
                "document_chunks.id",
                "document_chunks.document_version_id",
                "document_chunks.organization_id",
                "document_chunks.project_id",
            ],
            name="fk_candidate_item_evidence_chunk_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_candidate_item_evidence_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_item_evidence"),
        sa.UniqueConstraint(
            "item_id", "chunk_id", "ordinal", name="uq_candidate_item_evidence_item_chunk_ordinal"
        ),
    )
    for column in ("organization_id", "project_id", "item_id", "source_version_id", "chunk_id"):
        op.create_index(f"ix_candidate_item_evidence_{column}", "candidate_item_evidence", [column])
    op.create_index(
        "ix_candidate_item_evidence_project_item",
        "candidate_item_evidence",
        ["organization_id", "project_id", "item_id"],
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_kind", sa.String(length=19), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("document_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("candidate_dataset_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        _utc_column("created_at"),
        _utc_column("updated_at"),
        sa.CheckConstraint(
            "((job_kind = 'parse' AND document_version_id IS NOT NULL AND candidate_dataset_id IS NULL) "
            "OR (job_kind = 'generate_candidates' AND document_version_id IS NULL AND candidate_dataset_id IS NOT NULL))",
            name=conv("ck_ingestion_jobs_job_resource_matches_kind"),
        ),
        sa.CheckConstraint(
            "job_kind IN ('parse', 'generate_candidates')",
            name=conv("ck_ingestion_jobs_ingestion_job_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'blocked', 'succeeded', 'partial', 'failed', 'cancelled')",
            name=conv("ck_ingestion_jobs_ingestion_job_status"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=conv("ck_ingestion_jobs_attempt_count_nonnegative")
        ),
        sa.CheckConstraint(
            "completed_units >= 0", name=conv("ck_ingestion_jobs_completed_units_nonnegative")
        ),
        sa.CheckConstraint(
            "total_units >= 0", name=conv("ck_ingestion_jobs_total_units_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_ingestion_jobs_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_ingestion_jobs_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_ingestion_jobs_document_version_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_dataset_id", "organization_id", "project_id"],
            [
                "candidate_datasets.id",
                "candidate_datasets.organization_id",
                "candidate_datasets.project_id",
            ],
            name="fk_ingestion_jobs_candidate_dataset_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_jobs"),
        sa.UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_ingestion_jobs_tenant_identity"
        ),
        sa.UniqueConstraint(
            "organization_id",
            "project_id",
            "job_kind",
            "idempotency_key",
            name="uq_ingestion_jobs_project_operation_idempotency",
        ),
    )
    for column in ("organization_id", "project_id", "document_version_id", "candidate_dataset_id"):
        op.create_index(f"ix_ingestion_jobs_{column}", "ingestion_jobs", [column])
    op.create_index(
        "ix_ingestion_jobs_project_status_created",
        "ingestion_jobs",
        ["organization_id", "project_id", "status", "created_at"],
    )
    op.create_index("ix_ingestion_jobs_status_updated", "ingestion_jobs", ["status", "updated_at"])

    op.create_table(
        "ingestion_job_attempts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("final_status", sa.String(length=9), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "attempt_number > 0", name=conv("ck_ingestion_job_attempts_attempt_number_positive")
        ),
        sa.CheckConstraint(
            "fencing_token > 0", name=conv("ck_ingestion_job_attempts_fencing_token_positive")
        ),
        sa.CheckConstraint(
            "final_status IN ('succeeded', 'partial', 'failed', 'blocked', 'cancelled')",
            name=conv("ck_ingestion_job_attempts_final_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_ingestion_job_attempts_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "organization_id", "project_id"],
            ["ingestion_jobs.id", "ingestion_jobs.organization_id", "ingestion_jobs.project_id"],
            name="fk_ingestion_job_attempts_job_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_ingestion_job_attempts_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_job_attempts"),
        sa.UniqueConstraint(
            "job_id", "attempt_number", name="uq_ingestion_job_attempts_job_number"
        ),
    )
    for column in ("organization_id", "project_id", "job_id"):
        op.create_index(f"ix_ingestion_job_attempts_{column}", "ingestion_job_attempts", [column])
    op.create_index(
        "ix_ingestion_job_attempts_project_finished",
        "ingestion_job_attempts",
        ["organization_id", "project_id", "finished_at"],
    )

    op.create_table(
        "ingestion_job_leases",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        _utc_column("updated_at"),
        sa.CheckConstraint(
            "attempt_number > 0", name=conv("ck_ingestion_job_leases_attempt_number_positive")
        ),
        sa.CheckConstraint(
            "fencing_token > 0", name=conv("ck_ingestion_job_leases_fencing_token_positive")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_ingestion_job_leases_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "organization_id", "project_id"],
            ["ingestion_jobs.id", "ingestion_jobs.organization_id", "ingestion_jobs.project_id"],
            name="fk_ingestion_job_leases_job_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_ingestion_job_leases_project_organization_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_job_leases"),
        sa.UniqueConstraint("job_id", name="uq_ingestion_job_leases_job"),
    )
    for column in ("organization_id", "project_id", "job_id"):
        op.create_index(f"ix_ingestion_job_leases_{column}", "ingestion_job_leases", [column])
    op.create_index(
        "ix_ingestion_job_leases_lease_expires_at", "ingestion_job_leases", ["lease_expires_at"]
    )

    op.create_foreign_key(
        "fk_documents_latest_version",
        "documents",
        "document_versions",
        ["latest_version_id", "organization_id", "project_id"],
        ["id", "organization_id", "project_id"],
        ondelete="RESTRICT",
    )

    for table in (
        "documents",
        "document_versions",
        "candidate_datasets",
        "candidate_dataset_items",
        "ingestion_jobs",
        "ingestion_job_leases",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION public.rag_eval_set_updated_at()
            """
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.rag_eval_prevent_ingestion_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'ingestion history is append-only'
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    for table in ("document_chunks", "candidate_item_evidence", "ingestion_job_attempts"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION public.rag_eval_prevent_ingestion_history_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_truncate_guard
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.rag_eval_prevent_ingestion_history_mutation()
            """
        )
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON TABLE {table} FROM PUBLIC")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.rag_eval_prevent_document_version_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'document version source bytes are immutable'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.document_id IS DISTINCT FROM NEW.document_id
                OR OLD.version_number IS DISTINCT FROM NEW.version_number
                OR OLD.sha256 IS DISTINCT FROM NEW.sha256
                OR OLD.byte_size IS DISTINCT FROM NEW.byte_size
                OR OLD.detected_mime IS DISTINCT FROM NEW.detected_mime
                OR OLD.storage_key IS DISTINCT FROM NEW.storage_key THEN
                RAISE EXCEPTION 'document version source bytes are immutable'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_versions_source_bytes_guard
        BEFORE UPDATE OR DELETE ON document_versions
        FOR EACH ROW
        EXECUTE FUNCTION public.rag_eval_prevent_document_version_mutation()
        """
    )
    op.execute("REVOKE DELETE ON TABLE document_versions FROM PUBLIC")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.rag_eval_prevent_generation_config_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'candidate generation config snapshots are immutable'
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_generation_configs_immutable_guard
        BEFORE UPDATE OR DELETE ON candidate_generation_configs
        FOR EACH ROW
        EXECUTE FUNCTION public.rag_eval_prevent_generation_config_mutation()
        """
    )
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON TABLE candidate_generation_configs FROM PUBLIC")


def downgrade() -> None:
    for table in (
        "documents",
        "document_versions",
        "candidate_datasets",
        "candidate_dataset_items",
        "ingestion_jobs",
        "ingestion_job_leases",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_set_updated_at ON {table}")
    op.execute(
        "DROP TRIGGER IF EXISTS document_versions_source_bytes_guard ON document_versions"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS candidate_generation_configs_immutable_guard ON candidate_generation_configs"
    )
    op.execute("DROP FUNCTION IF EXISTS public.rag_eval_prevent_document_version_mutation()")
    op.execute("DROP FUNCTION IF EXISTS public.rag_eval_prevent_generation_config_mutation()")
    for table in ("document_chunks", "candidate_item_evidence", "ingestion_job_attempts"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_truncate_guard ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS public.rag_eval_prevent_ingestion_history_mutation()")
    op.drop_constraint("fk_documents_latest_version", "documents", type_="foreignkey")
    for table in (
        "ingestion_job_leases",
        "ingestion_job_attempts",
        "ingestion_jobs",
        "candidate_item_evidence",
        "candidate_dataset_items",
        "candidate_generation_configs",
        "candidate_datasets",
        "document_chunks",
        "document_versions",
        "documents",
    ):
        op.drop_table(table)
