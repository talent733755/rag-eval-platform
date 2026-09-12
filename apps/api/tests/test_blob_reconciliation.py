from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.models import (
    Base,
    Document,
    DocumentParseStatus,
    DocumentVersion,
    Organization,
    Project,
)
from rag_eval_api.services.blob_reconciliation import reconcile_orphaned_blobs
from rag_eval_api.storage.errors import BlobStoreError
from rag_eval_api.storage.protocol import BlobObject


class FakeBlobStore:
    def __init__(self, objects: list[BlobObject], failing_key: str | None = None) -> None:
        self.objects = objects
        self.failing_key = failing_key
        self.deleted: list[str] = []

    def iter_objects(self):
        return iter(self.objects)

    def delete(self, storage_key: str) -> None:
        if storage_key == self.failing_key:
            raise BlobStoreError("delete failed")
        self.deleted.append(storage_key)


@pytest_asyncio.fixture
async def reconciliation_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    organization = Organization(name="Reconciliation Org", slug=f"reconcile-{uuid4()}")
    project = Project(
        name="Reconciliation Project", slug=f"project-{uuid4()}", organization=organization
    )
    document = Document(
        organization=organization,
        project=project,
        display_name="referenced.md",
        source_type="markdown",
    )
    document_version = DocumentVersion(
        organization=organization,
        project=project,
        document=document,
        version_number=1,
        sha256="a" * 64,
        byte_size=10,
        detected_mime="text/markdown",
        storage_key="a" * 16 + "/" + "b" * 32,
        parse_status=DocumentParseStatus.queued,
    )
    async with session_factory() as session:
        session.add_all([organization, project, document, document_version])
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_orphaned_blobs_respects_references_and_grace_period(
    reconciliation_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    referenced_key = "a" * 16 + "/" + "b" * 32
    old_orphan_key = "c" * 16 + "/" + "d" * 32
    recent_orphan_key = "e" * 16 + "/" + "f" * 32
    failed_orphan_key = "g" * 16 + "/" + "h" * 32
    store = FakeBlobStore(
        [
            BlobObject(referenced_key, 10, now - timedelta(days=30)),
            BlobObject(old_orphan_key, 11, now - timedelta(days=2)),
            BlobObject(recent_orphan_key, 12, now - timedelta(minutes=5)),
            BlobObject(failed_orphan_key, 13, now - timedelta(days=2)),
        ],
        failing_key=failed_orphan_key,
    )

    result = await reconcile_orphaned_blobs(
        reconciliation_session,
        store,  # type: ignore[arg-type]
        grace_period=timedelta(days=1),
        now=now,
    )

    assert result.scanned == 4
    assert result.referenced == 1
    assert result.skipped_recent == 1
    assert result.deleted == 1
    assert result.delete_failed == 1
    assert store.deleted == [old_orphan_key]
