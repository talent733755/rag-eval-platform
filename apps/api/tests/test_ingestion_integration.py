"""PostgreSQL-only tests for the document ingestion persistence contract."""

import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


@pytest.fixture
def integration_database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.fail("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest_asyncio.fixture
async def postgres_connection(integration_database_url: str):
    engine = create_async_engine(integration_database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            yield connection
    finally:
        await engine.dispose()


async def _assert_db_failure(
    connection: AsyncConnection,
    statement: object,
    parameters: dict[str, object],
    exception: type[Exception] = DBAPIError,
) -> None:
    savepoint = await connection.begin_nested()
    try:
        with pytest.raises(exception):
            await connection.execute(statement, parameters)  # type: ignore[arg-type]
    finally:
        if savepoint.is_active:
            await savepoint.rollback()


async def _seed_tenant(connection: AsyncConnection) -> tuple[UUID, UUID]:
    organization_id, project_id = uuid4(), uuid4()
    await connection.execute(
        text("INSERT INTO organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": organization_id, "name": "Integration org", "slug": f"org-{organization_id}"},
    )
    await connection.execute(
        text(
            "INSERT INTO projects (id, organization_id, name, slug) "
            "VALUES (:id, :organization_id, :name, :slug)"
        ),
        {
            "id": project_id,
            "organization_id": organization_id,
            "name": "Integration project",
            "slug": f"project-{project_id}",
        },
    )
    return organization_id, project_id


async def _insert_document_version(
    connection: AsyncConnection,
    organization_id: UUID,
    project_id: UUID,
    *,
    sha256: str,
    byte_size: int = 10,
) -> tuple[UUID, UUID, UUID]:
    document_id, version_id = uuid4(), uuid4()
    await connection.execute(
        text(
            "INSERT INTO documents "
            "(id, organization_id, project_id, display_name, source_type) "
            "VALUES (:id, :organization_id, :project_id, :display_name, 'markdown')"
        ),
        {
            "id": document_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "display_name": f"document-{document_id}.md",
        },
    )
    await connection.execute(
        text(
            "INSERT INTO document_versions "
            "(id, organization_id, project_id, document_id, version_number, sha256, byte_size, "
            "detected_mime, storage_key, parse_status) VALUES "
            "(:id, :organization_id, :project_id, :document_id, 1, :sha256, :byte_size, "
            "'text/markdown', :storage_key, 'queued')"
        ),
        {
            "id": version_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "document_id": document_id,
            "sha256": sha256,
            "byte_size": byte_size,
            "storage_key": f"private/{version_id}",
        },
    )
    return document_id, version_id, uuid4()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_migration_head_and_ingestion_tables(
    postgres_connection: AsyncConnection,
) -> None:
    revision = await postgres_connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "0002_document_ingestion"
    result = await postgres_connection.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name IN "
            "('documents', 'document_versions', 'document_chunks', "
            "'candidate_generation_configs', 'candidate_dataset_items', "
            "'candidate_item_evidence', 'ingestion_jobs', "
            "'ingestion_job_attempts', 'ingestion_job_leases')"
        )
    )
    assert result.scalar_one() == 9


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_content_identity_tenant_fk_and_immutable_version(
    integration_database_url: str,
) -> None:
    engine = create_async_engine(integration_database_url, pool_pre_ping=True)
    sha256 = "a" * 64
    try:
        async with engine.begin() as connection:
            organization_id, project_id = await _seed_tenant(connection)
            document_id, version_id, _ = await _insert_document_version(
                connection, organization_id, project_id, sha256=sha256
            )
            await connection.execute(
                text("UPDATE document_versions SET parse_status = 'processing' WHERE id = :id"),
                {"id": version_id},
            )
            await _assert_db_failure(
                connection,
                text("UPDATE document_versions SET sha256 = :sha256 WHERE id = :id"),
                {"id": version_id, "sha256": "b" * 64},
            )
        async with engine.begin() as connection:
            organization_id, project_id = await _seed_tenant(connection)
            await _insert_document_version(connection, organization_id, project_id, sha256=sha256)
            savepoint = await connection.begin_nested()
            try:
                with pytest.raises(IntegrityError):
                    await _insert_document_version(
                        connection, organization_id, project_id, sha256=sha256
                    )
            finally:
                if savepoint.is_active:
                    await savepoint.rollback()
        async with engine.begin() as connection:
            organization_id, project_id = await _seed_tenant(connection)
            _, version_id, _ = await _insert_document_version(
                connection, organization_id, project_id, sha256="c" * 64
            )
            await _assert_db_failure(
                connection,
                text("DELETE FROM document_versions WHERE id = :id"),
                {"id": version_id},
            )
            await _assert_db_failure(
                connection,
                text(
                    "INSERT INTO document_versions "
                    "(id, organization_id, project_id, document_id, version_number, sha256, "
                    "byte_size, detected_mime, storage_key, parse_status) VALUES "
                    "(:id, :organization_id, :project_id, :document_id, 1, :sha256, 1, "
                    "'text/plain', 'private/invalid', 'queued')"
                ),
                {
                    "id": uuid4(),
                    "organization_id": organization_id,
                    "project_id": project_id,
                    "document_id": document_id,
                    "sha256": "not-a-sha",
                },
                IntegrityError,
            )
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_candidate_traceability_and_config_immutability(
    postgres_connection: AsyncConnection,
) -> None:
    organization_id, project_id = await _seed_tenant(postgres_connection)
    _, version_id, _ = await _insert_document_version(
        postgres_connection, organization_id, project_id, sha256="d" * 64
    )
    chunk_id = uuid4()
    await postgres_connection.execute(
        text(
            "INSERT INTO document_chunks "
            "(id, organization_id, project_id, document_version_id, ordinal, content, content_hash, "
            "source_location, character_count, token_count) VALUES "
            "(:id, :organization_id, :project_id, :version_id, 0, 'context', :hash, '{}', 7, 2)"
        ),
        {
            "id": chunk_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "version_id": version_id,
            "hash": "e" * 64,
        },
    )
    dataset_id, config_id, item_id = uuid4(), uuid4(), uuid4()
    await postgres_connection.execute(
        text(
            "INSERT INTO candidate_datasets "
            "(id, organization_id, project_id, name, status) VALUES "
            "(:id, :organization_id, :project_id, 'Dataset', 'draft')"
        ),
        {"id": dataset_id, "organization_id": organization_id, "project_id": project_id},
    )
    await postgres_connection.execute(
        text(
            "INSERT INTO candidate_generation_configs "
            "(id, organization_id, project_id, dataset_id, capability_version, provider_name, "
            "model_name, prompt_version, requested_version_ids, chunk_content_hashes, environment, "
            "request_id, usage) VALUES (:id, :organization_id, :project_id, :dataset_id, "
            "'candidate-generation/v1', 'test', 'test-model', 'prompt-v1', "
            "CAST(:versions AS JSON), CAST(:hashes AS JSON), CAST(:environment AS JSON), 'request', '{}')"
        ),
        {
            "id": config_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "versions": json.dumps([str(version_id)]),
            "hashes": json.dumps(["e" * 64]),
            "environment": json.dumps({"test": True}),
        },
    )
    await postgres_connection.execute(
        text(
            "INSERT INTO candidate_dataset_items "
            "(id, organization_id, project_id, dataset_id, generation_config_id, source_version_id, "
            "question, question_type, reference_answer, confidence, automatic_checks, review_status, provenance) "
            "VALUES (:id, :organization_id, :project_id, :dataset_id, :config_id, :version_id, "
            "'What?', 'single_answer', 'Answer', 0.9, '{}', 'pending', '{}')"
        ),
        {
            "id": item_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "config_id": config_id,
            "version_id": version_id,
        },
    )
    await postgres_connection.execute(
        text(
            "INSERT INTO candidate_item_evidence "
            "(id, organization_id, project_id, item_id, source_version_id, chunk_id, ordinal, excerpt) "
            "VALUES (:id, :organization_id, :project_id, :item_id, :version_id, :chunk_id, 0, 'context')"
        ),
        {
            "id": uuid4(),
            "organization_id": organization_id,
            "project_id": project_id,
            "item_id": item_id,
            "version_id": version_id,
            "chunk_id": chunk_id,
        },
    )
    await _assert_db_failure(
        postgres_connection,
        text(
            "INSERT INTO candidate_item_evidence "
            "(id, organization_id, project_id, item_id, source_version_id, chunk_id, ordinal) "
            "VALUES (:id, :organization_id, :project_id, :item_id, :version_id, :chunk_id, 1)"
        ),
        {
            "id": uuid4(),
            "organization_id": organization_id,
            "project_id": project_id,
            "item_id": item_id,
            "version_id": uuid4(),
            "chunk_id": chunk_id,
        },
        IntegrityError,
    )
    await _assert_db_failure(
        postgres_connection,
        text("UPDATE candidate_generation_configs SET model_name = 'mutated' WHERE id = :id"),
        {"id": config_id},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_job_status_final_history_and_lease_fencing(
    postgres_connection: AsyncConnection,
) -> None:
    organization_id, project_id = await _seed_tenant(postgres_connection)
    _, version_id, _ = await _insert_document_version(
        postgres_connection, organization_id, project_id, sha256="f" * 64
    )
    job_id = uuid4()
    await postgres_connection.execute(
        text(
            "INSERT INTO ingestion_jobs "
            "(id, organization_id, project_id, job_kind, status, document_version_id, "
            "idempotency_key, request_fingerprint) VALUES "
            "(:id, :organization_id, :project_id, 'parse', 'queued', :version_id, 'key', 'fingerprint')"
        ),
        {
            "id": job_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "version_id": version_id,
        },
    )
    now = datetime.now(UTC)
    attempt_values = {
        "id": uuid4(),
        "organization_id": organization_id,
        "project_id": project_id,
        "job_id": job_id,
        "started_at": now,
        "finished_at": now,
    }
    await _assert_db_failure(
        postgres_connection,
        text(
            "INSERT INTO ingestion_job_attempts "
            "(id, organization_id, project_id, job_id, attempt_number, worker_id, final_status, "
            "started_at, finished_at, input_snapshot, retryable, fencing_token) VALUES "
            "(:id, :organization_id, :project_id, :job_id, 1, 'worker', 'processing', "
            ":started_at, :finished_at, '{}', true, 1)"
        ),
        attempt_values,
        IntegrityError,
    )
    attempt_values["id"] = uuid4()
    await postgres_connection.execute(
        text(
            "INSERT INTO ingestion_job_attempts "
            "(id, organization_id, project_id, job_id, attempt_number, worker_id, final_status, "
            "started_at, finished_at, input_snapshot, retryable, fencing_token) VALUES "
            "(:id, :organization_id, :project_id, :job_id, 1, 'worker', 'failed', "
            ":started_at, :finished_at, '{}', true, 1)"
        ),
        attempt_values,
    )
    await _assert_db_failure(
        postgres_connection,
        text("DELETE FROM ingestion_job_attempts WHERE id = :id"),
        {"id": attempt_values["id"]},
    )
    lease_id = uuid4()
    await postgres_connection.execute(
        text(
            "INSERT INTO ingestion_job_leases "
            "(id, organization_id, project_id, job_id, attempt_number, worker_id, lease_expires_at, "
            "heartbeat_at, fencing_token) VALUES (:id, :organization_id, :project_id, :job_id, 1, "
            "'worker', :expires, :heartbeat, 1)"
        ),
        {
            "id": lease_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "job_id": job_id,
            "expires": now,
            "heartbeat": now,
        },
    )
    stale = await postgres_connection.execute(
        text(
            "UPDATE ingestion_job_leases SET heartbeat_at = :heartbeat, fencing_token = 2 "
            "WHERE id = :id AND fencing_token = 0"
        ),
        {"id": lease_id, "heartbeat": now},
    )
    assert stale.rowcount == 0
