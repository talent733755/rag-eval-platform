from sqlalchemy import BigInteger, CheckConstraint, UniqueConstraint

from rag_eval_api.models import (
    Base,
    CandidateDatasetItem,
    CandidateGenerationConfig,
    CandidateItemEvidence,
    Document,
    DocumentChunk,
    DocumentParseStatus,
    DocumentSourceType,
    DocumentVersion,
    IngestionAttemptFinalStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobKind,
    IngestionJobLease,
    IngestionJobStatus,
)


def test_document_ingestion_models_are_registered_with_tenant_columns() -> None:
    expected = {
        "documents",
        "document_versions",
        "document_chunks",
        "candidate_datasets",
        "candidate_generation_configs",
        "candidate_dataset_items",
        "candidate_item_evidence",
        "ingestion_jobs",
        "ingestion_job_attempts",
        "ingestion_job_leases",
    }
    assert expected <= set(Base.metadata.tables)
    for table_name in expected:
        table = Base.metadata.tables[table_name]
        assert {"organization_id", "project_id"} <= {column.name for column in table.c}


def test_ingestion_model_constraints_cover_idempotency_and_immutable_history() -> None:
    jobs = IngestionJob.__table__
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns}
        == {"organization_id", "project_id", "job_kind", "idempotency_key"}
        for constraint in jobs.constraints
    )
    assert any(isinstance(constraint, CheckConstraint) for constraint in jobs.constraints)
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"job_id", "attempt_number"}
        for constraint in IngestionJobAttempt.__table__.constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"item_id", "chunk_id", "ordinal"}
        for constraint in CandidateItemEvidence.__table__.constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns}
        == {"id", "organization_id", "project_id"}
        for constraint in IngestionJob.__table__.constraints
    )
    assert CandidateDatasetItem.__table__.c.generation_config_id is not None
    assert CandidateItemEvidence.__table__.c.source_version_id is not None
    assert isinstance(DocumentVersion.__table__.c.byte_size.type, BigInteger)
    assert isinstance(IngestionJobLease.__table__.c.fencing_token.type, BigInteger)
    assert IngestionJob.__table__.c.status.type.length == 10
    assert IngestionJobAttempt.__table__.c.final_status.type.length == 10
    assert any(
        isinstance(constraint, CheckConstraint) and "sha256" in str(constraint.sqltext)
        for constraint in DocumentVersion.__table__.constraints
    )
    assert any(
        isinstance(constraint, CheckConstraint) and "content_hash" in str(constraint.sqltext)
        for constraint in DocumentChunk.__table__.constraints
    )
    assert Document.__table__.c.latest_version_id.nullable
    assert DocumentVersion.__table__.c.storage_key.unique is not True
    assert DocumentChunk.__table__.c.content_hash is not None
    assert CandidateDatasetItem.__table__.c.source_version_id is not None
    assert CandidateGenerationConfig.__table__.c.capability_version is not None
    assert IngestionJobLease.__table__.c.fencing_token is not None


def test_public_ingestion_enums_have_stable_wire_values() -> None:
    assert {member.value for member in DocumentSourceType} == {"pdf", "docx", "markdown", "txt"}
    assert {member.value for member in DocumentParseStatus} == {
        "queued",
        "processing",
        "succeeded",
        "failed",
        "cancelled",
    }
    assert {member.value for member in IngestionJobKind} == {"parse", "generate_candidates"}
    assert {member.value for member in IngestionJobStatus} == {
        "queued",
        "processing",
        "blocked",
        "succeeded",
        "partial",
        "failed",
        "cancelled",
    }
    assert {member.value for member in IngestionAttemptFinalStatus} == {
        "succeeded",
        "partial",
        "failed",
        "blocked",
        "cancelled",
    }
