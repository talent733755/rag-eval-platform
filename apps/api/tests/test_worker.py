from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.models import (
    AuditEvent,
    Base,
    Document,
    DocumentChunk,
    DocumentParseStatus,
    DocumentVersion,
    IngestionAttemptFinalStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobKind,
    IngestionJobLease,
    IngestionJobStatus,
    Organization,
    Project,
)
from rag_eval_api.parsers.errors import MalformedDocumentError
from rag_eval_api.parsers.models import CanonicalChunk, ParseResult
from rag_eval_api.services.worker import IngestionWorker, MaintenanceResult, WorkerBatchResult
from rag_eval_api.storage.local import LocalBlobStore


class SuccessfulParser:
    def parse(self, source: BytesIO, **_: object) -> ParseResult:
        data = source.read()
        content = data.decode("utf-8")
        return ParseResult(
            parser_version="test-v1",
            content_hash=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            page_count=0,
            paragraph_count=1,
            chunks=(
                CanonicalChunk.create(ordinal=0, content=content, source_location={"line": 1}),
            ),
        )


class FailingParser:
    def parse(self, source: BytesIO, **_: object) -> ParseResult:
        del source
        raise MalformedDocumentError("malformed test document")


@dataclass(frozen=True)
class WorkerFixture:
    session_factory: async_sessionmaker[AsyncSession]
    blob_store: LocalBlobStore
    job_id: UUID
    version_id: UUID


@pytest_asyncio.fixture
async def worker_fixture(tmp_path) -> AsyncIterator[WorkerFixture]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    payload = b"# worker document\n"
    blob_store = LocalBlobStore(tmp_path / "blobs")
    stored = blob_store.put(BytesIO(payload))
    organization = Organization(name="Worker Org", slug=f"worker-{uuid4()}")
    project = Project(name="Worker Project", slug=f"project-{uuid4()}", organization=organization)
    document = Document(
        organization=organization,
        project=project,
        display_name="worker.md",
        source_type="markdown",
    )
    version = DocumentVersion(
        organization=organization,
        project=project,
        document=document,
        version_number=1,
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        detected_mime="text/markdown",
        storage_key=stored.storage_key,
        parse_status=DocumentParseStatus.queued,
    )
    job = IngestionJob(
        organization=organization,
        project=project,
        job_kind=IngestionJobKind.parse,
        status=IngestionJobStatus.queued,
        document_version=version,
        idempotency_key="worker-test",
        request_fingerprint="worker-fingerprint",
    )
    async with session_factory() as session:
        session.add_all([organization, project, document, version, job])
        await session.flush()
        document.latest_version_id = version.id
        await session.commit()
        fixture = WorkerFixture(session_factory, blob_store, job.id, version.id)

    try:
        yield fixture
    finally:
        blob_store.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_worker_parses_blob_and_persists_immutable_chunks(
    worker_fixture: WorkerFixture,
) -> None:
    worker = IngestionWorker(
        session_factory=worker_fixture.session_factory,
        blob_store=worker_fixture.blob_store,
        parser_registry=SuccessfulParser(),  # type: ignore[arg-type]
        worker_id="worker-test",
    )

    assert await worker.run_once() is True

    async with worker_fixture.session_factory() as session:
        job = await session.scalar(
            select(IngestionJob).where(IngestionJob.id == worker_fixture.job_id)
        )
        version = await session.scalar(
            select(DocumentVersion).where(DocumentVersion.id == worker_fixture.version_id)
        )
        chunks = list(
            (
                await session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_version_id == worker_fixture.version_id
                    )
                )
            ).all()
        )
        attempt = await session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == worker_fixture.job_id)
        )
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.resource_id == str(worker_fixture.job_id))
        )

    assert job is not None and job.status is IngestionJobStatus.succeeded
    assert version is not None and version.parse_status is DocumentParseStatus.succeeded
    assert len(chunks) == 1
    assert chunks[0].content == "# worker document\n"
    assert attempt is not None and attempt.final_status is IngestionAttemptFinalStatus.succeeded
    assert audit is not None and audit.action == "ingestion.succeeded"


@pytest.mark.asyncio
async def test_worker_classifies_parser_failure_and_preserves_attempt_history(
    worker_fixture: WorkerFixture,
) -> None:
    worker = IngestionWorker(
        session_factory=worker_fixture.session_factory,
        blob_store=worker_fixture.blob_store,
        parser_registry=FailingParser(),  # type: ignore[arg-type]
        worker_id="worker-test",
    )

    assert await worker.run_once() is True

    async with worker_fixture.session_factory() as session:
        job = await session.scalar(
            select(IngestionJob).where(IngestionJob.id == worker_fixture.job_id)
        )
        version = await session.scalar(
            select(DocumentVersion).where(DocumentVersion.id == worker_fixture.version_id)
        )
        attempt = await session.scalar(
            select(IngestionJobAttempt).where(IngestionJobAttempt.job_id == worker_fixture.job_id)
        )

    assert job is not None
    assert job.status is IngestionJobStatus.failed
    assert job.last_error_code == "parse_failed"
    assert version is not None and version.parse_status is DocumentParseStatus.failed
    assert attempt is not None
    assert attempt.final_status is IngestionAttemptFinalStatus.failed
    assert attempt.error_code == "parse_failed"


@pytest.mark.asyncio
async def test_worker_requeues_expired_lease_and_increments_fencing_token(
    worker_fixture: WorkerFixture,
) -> None:
    worker = IngestionWorker(
        session_factory=worker_fixture.session_factory,
        blob_store=worker_fixture.blob_store,
        parser_registry=SuccessfulParser(),  # type: ignore[arg-type]
        worker_id="worker-test",
    )

    claim = await worker._claim_next()
    assert claim is not None
    async with worker_fixture.session_factory() as session:
        lease = await session.scalar(
            select(IngestionJobLease).where(IngestionJobLease.job_id == worker_fixture.job_id)
        )
        assert lease is not None
        lease.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    assert await worker.recover_expired_jobs() == 1
    assert await worker.run_once() is True

    async with worker_fixture.session_factory() as session:
        job = await session.scalar(
            select(IngestionJob).where(IngestionJob.id == worker_fixture.job_id)
        )
        lease = await session.scalar(
            select(IngestionJobLease).where(IngestionJobLease.job_id == worker_fixture.job_id)
        )
        attempts = list(
            (
                await session.scalars(
                    select(IngestionJobAttempt)
                    .where(IngestionJobAttempt.job_id == worker_fixture.job_id)
                    .order_by(IngestionJobAttempt.attempt_number)
                )
            ).all()
        )

    assert job is not None and job.status is IngestionJobStatus.succeeded
    assert lease is not None and lease.fencing_token == 2
    assert len(attempts) == 1
    assert attempts[0].attempt_number == 2


@pytest.mark.asyncio
async def test_worker_heartbeat_renews_only_the_current_lease(
    worker_fixture: WorkerFixture,
) -> None:
    worker = IngestionWorker(
        session_factory=worker_fixture.session_factory,
        blob_store=worker_fixture.blob_store,
        parser_registry=SuccessfulParser(),  # type: ignore[arg-type]
        worker_id="worker-test",
        lease_ttl=timedelta(seconds=60),
    )

    claim = await worker._claim_next()
    assert claim is not None

    assert await worker.heartbeat(claim.job_id, claim.lease_id, claim.fencing_token) is True
    assert await worker.heartbeat(claim.job_id, claim.lease_id, claim.fencing_token + 1) is False


@pytest.mark.asyncio
async def test_worker_process_batch_and_maintenance_return_structured_counts(
    worker_fixture: WorkerFixture,
) -> None:
    worker = IngestionWorker(
        session_factory=worker_fixture.session_factory,
        blob_store=worker_fixture.blob_store,
        parser_registry=SuccessfulParser(),  # type: ignore[arg-type]
        worker_id="worker-test",
        orphan_blob_grace_period=timedelta(hours=1),
    )

    batch = await worker.process_batch(2)
    maintenance = await worker.run_maintenance()

    assert isinstance(batch, WorkerBatchResult)
    assert batch.processed == 1
    assert batch.succeeded == 1
    assert batch.failed == 0
    assert isinstance(maintenance, MaintenanceResult)
    assert maintenance.recovered_jobs == 0
    assert maintenance.failed_count == 0
    assert maintenance.duration_ms >= 0
