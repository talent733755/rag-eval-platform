from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from io import BufferedReader
from typing import BinaryIO
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.auth.context import RequestActor, get_current_actor
from rag_eval_api.config import DEFAULT_REDIS_URL, DEFAULT_SECRET_KEY, Settings
from rag_eval_api.db import get_db_session
from rag_eval_api.main import create_app
from rag_eval_api.models import (
    AuditEvent,
    Base,
    Document,
    DocumentVersion,
    IngestionJob,
    Membership,
    MembershipRole,
    Organization,
    Project,
)
from rag_eval_api.storage.protocol import StoredBlob

EDITOR_ID = UUID("00000000-0000-0000-0000-000000000201")
VIEWER_ID = UUID("00000000-0000-0000-0000-000000000202")


@dataclass
class FakeBlobStore:
    blobs: dict[str, bytes] = field(default_factory=dict)
    calls: int = 0

    def put(
        self,
        source: BinaryIO,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> StoredBlob:
        self.calls += 1
        data = source.read()
        if not data:
            raise ValueError("blob must not be empty")
        if max_bytes is not None and len(data) > max_bytes:
            raise ValueError("blob exceeds the configured size limit")
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("blob checksum does not match the declared digest")
        key = f"fake/{uuid4()}"
        self.blobs[key] = data
        return StoredBlob(storage_key=key, byte_size=len(data), sha256=digest)

    def open(self, storage_key: str) -> AbstractContextManager[BufferedReader]:
        raise NotImplementedError

    def exists(self, storage_key: str) -> bool:
        return storage_key in self.blobs

    def delete(self, storage_key: str) -> None:
        self.blobs.pop(storage_key, None)


@dataclass(frozen=True)
class Seed:
    organization_id: UUID
    project_id: UUID
    other_project_id: UUID


@pytest_asyncio.fixture
async def document_api_environment() -> AsyncIterator[
    tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(
        dbapi_connection: sqlite3.Connection,
        connection_record: object,
    ) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    organization = Organization(name="Upload Org", slug=f"upload-{uuid4()}")
    project = Project(name="Upload Project", slug=f"project-{uuid4()}", organization=organization)
    other_project = Project(
        name="Other Project", slug=f"other-{uuid4()}", organization=organization
    )
    project.memberships.extend(
        [
            Membership(organization=organization, user_id=EDITOR_ID, role=MembershipRole.editor),
            Membership(organization=organization, user_id=VIEWER_ID, role=MembershipRole.viewer),
        ]
    )
    async with session_factory() as session:
        session.add_all([organization, project, other_project])
        await session.commit()
        seed = Seed(
            organization_id=organization.id,
            project_id=project.id,
            other_project_id=other_project.id,
        )

    settings = Settings(
        database_url="postgresql+asyncpg://rag_eval:change-me@localhost:5432/rag_eval",
        redis_url=DEFAULT_REDIS_URL,
        app_env="development",
        cors_origins=["http://localhost:3000"],
        log_level="INFO",
        secret_key=SecretStr(DEFAULT_SECRET_KEY),
        max_upload_bytes=32,
        _env_file=None,  # type: ignore[call-arg]
    )
    application = create_app(settings=settings)
    blob_store = FakeBlobStore()
    application.state.blob_store = blob_store
    current_actor = RequestActor(user_id=VIEWER_ID, organization_id=seed.organization_id)
    application.dependency_overrides[get_current_actor] = lambda: current_actor

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session

    def set_actor(user_id: UUID) -> None:
        nonlocal current_actor
        current_actor = RequestActor(user_id=user_id, organization_id=seed.organization_id)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            yield client, seed, set_actor, session_factory, blob_store
    finally:
        application.dependency_overrides.clear()
        await application.state.db_engine.dispose()
        await application.state.redis_client.aclose()
        await engine.dispose()


def upload(
    client: httpx.AsyncClient,
    project_id: UUID,
    *,
    key: str,
    filename: str = "handbook.md",
    content: bytes = b"# Handbook\n\nUse the API.\n",
) -> httpx.Response:
    return client.post(
        f"/api/projects/{project_id}/documents",
        headers={"Idempotency-Key": key},
        files={"file": (filename, content, "text/markdown")},
    )


@pytest.mark.asyncio
async def test_editor_upload_creates_tenant_scoped_records_and_audit(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, blob_store = document_api_environment
    set_actor(EDITOR_ID)

    response = await upload(client, seed.project_id, key="upload-1")

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"document", "document_version", "ingestion_job"}
    assert body["document"]["organization_id"] == str(seed.organization_id)
    assert body["document"]["project_id"] == str(seed.project_id)
    assert body["document"]["source_type"] == "markdown"
    assert body["document_version"]["parse_status"] == "queued"
    assert body["document_version"]["storage_key"].startswith("fake/")
    assert body["ingestion_job"]["status"] == "queued"
    assert body["ingestion_job"]["job_kind"] == "parse"
    assert blob_store.calls == 1

    async with session_factory() as session:
        assert (
            await session.scalar(
                select(Document).where(
                    Document.id == UUID(body["document"]["id"]),
                    Document.organization_id == seed.organization_id,
                    Document.project_id == seed.project_id,
                )
            )
            is not None
        )
        assert (
            await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.id == UUID(body["document_version"]["id"]),
                    DocumentVersion.project_id == seed.project_id,
                )
            )
            is not None
        )
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.resource_id == body["document"]["id"])
        )
        assert audit is not None
        assert audit.action == "document.uploaded"
        assert audit.actor_id == EDITOR_ID


@pytest.mark.asyncio
async def test_viewer_cannot_upload_and_project_access_is_tenant_scoped(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, _, blob_store = document_api_environment

    denied = await upload(client, seed.project_id, key="viewer-upload")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"
    assert blob_store.calls == 0

    set_actor(EDITOR_ID)
    cross_project = await upload(client, seed.other_project_id, key="cross-project")
    assert cross_project.status_code == 403
    assert blob_store.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content", "expected_status", "expected_code"),
    [
        ("payload.exe", b"data", 415, "unsupported_type"),
        ("empty.md", b"", 413, "size_exceeded"),
        ("too-large.md", b"1" * 33, 413, "size_exceeded"),
    ],
)
async def test_upload_rejects_unsupported_empty_and_oversized_files(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
    filename: str,
    content: bytes,
    expected_status: int,
    expected_code: str,
) -> None:
    client, seed, set_actor, _, blob_store = document_api_environment
    set_actor(EDITOR_ID)

    response = await upload(
        client,
        seed.project_id,
        key=f"reject-{filename}",
        filename=filename,
        content=content,
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert blob_store.calls == 0


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_and_conflicting_fingerprint_is_rejected(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, blob_store = document_api_environment
    set_actor(EDITOR_ID)

    first = await upload(client, seed.project_id, key="same-key", content=b"first")
    replay = await upload(client, seed.project_id, key="same-key", content=b"first")
    conflict = await upload(client, seed.project_id, key="same-key", content=b"second")

    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
    assert blob_store.calls == 1
    async with session_factory() as session:
        assert len((await session.scalars(select(Document))).all()) == 1
        assert len((await session.scalars(select(IngestionJob))).all()) == 1


@pytest.mark.asyncio
async def test_same_project_content_returns_duplicate_document_without_new_blob(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, blob_store = document_api_environment
    set_actor(EDITOR_ID)

    first = await upload(client, seed.project_id, key="first-content", content=b"same")
    duplicate = await upload(client, seed.project_id, key="second-content", content=b"same")

    assert first.status_code == 202
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_document"
    assert duplicate.json()["error"]["details"]["document_id"] == first.json()["document"]["id"]
    assert blob_store.calls == 1
    async with session_factory() as session:
        assert len((await session.scalars(select(Document))).all()) == 1
        assert len((await session.scalars(select(DocumentVersion))).all()) == 1
