from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.models import (
    Document,
    DocumentChunk,
    DocumentParseStatus,
    DocumentVersion,
    IngestionJob,
    IngestionJobKind,
    IngestionJobStatus,
    Organization,
    Project,
)
from rag_eval_api.parsers.models import CanonicalChunk, ParseResult
from rag_eval_api.services.worker import IngestionWorker
from rag_eval_api.storage.local import LocalBlobStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL is required for worker integration tests",
    ),
]


class SuccessfulParser:
    def parse(self, source: BytesIO, **_: object) -> ParseResult:
        data = source.read()
        return ParseResult(
            parser_version="integration-test-v1",
            content_hash=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            page_count=0,
            paragraph_count=1,
            chunks=(
                CanonicalChunk.create(
                    ordinal=0,
                    content=data.decode("utf-8"),
                    source_location={"line": 1},
                ),
            ),
        )


@dataclass(frozen=True)
class SeededJob:
    job_id: UUID
    version_id: UUID


@pytest_asyncio.fixture
async def postgres_worker_environment(
    tmp_path: Path,
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], LocalBlobStore, list[SeededJob]]]:
    database_url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    blob_store = LocalBlobStore(tmp_path / "blobs")
    organization = Organization(name="Worker integration org", slug=f"worker-{uuid4()}")
    project = Project(
        name="Worker integration project",
        slug=f"project-{uuid4()}",
        organization=organization,
    )
    seeded: list[SeededJob] = []
    async with session_factory() as session:
        session.add_all([organization, project])
        await session.flush()
        for index in range(2):
            payload = f"# integration document {index}\n".encode()
            stored = blob_store.put(BytesIO(payload))
            document = Document(
                organization=organization,
                project=project,
                display_name=f"worker-{index}.md",
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
                idempotency_key=f"worker-integration-{index}",
                request_fingerprint=f"worker-fingerprint-{index}",
            )
            session.add_all([document, version, job])
            await session.flush()
            document.latest_version_id = version.id
            seeded.append(SeededJob(job.id, version.id))
        await session.commit()
    try:
        yield session_factory, blob_store, seeded
    finally:
        blob_store.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_worker_processes_two_jobs_once_concurrently(
    postgres_worker_environment: tuple[
        async_sessionmaker[AsyncSession], LocalBlobStore, list[SeededJob]
    ],
) -> None:
    session_factory, blob_store, seeded = postgres_worker_environment
    workers = [
        IngestionWorker(
            session_factory=session_factory,
            blob_store=blob_store,
            parser_registry=SuccessfulParser(),  # type: ignore[arg-type]
            worker_id=f"integration-worker-{index}",
        )
        for index in range(2)
    ]

    assert await asyncio.gather(*(worker.run_once() for worker in workers)) == [True, True]

    async with session_factory() as session:
        jobs = list(
            (
                await session.scalars(
                    select(IngestionJob).where(
                        IngestionJob.id.in_([item.job_id for item in seeded])
                    )
                )
            ).all()
        )
        chunks = list(
            (
                await session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_version_id.in_([item.version_id for item in seeded])
                    )
                )
            ).all()
        )

    assert {job.status for job in jobs} == {IngestionJobStatus.succeeded}
    assert len(chunks) == 2
