from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import timedelta
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
from rag_eval_api.auth.rbac import ProjectAccess
from rag_eval_api.candidates.fake import FakeCandidateGenerator
from rag_eval_api.config import DEFAULT_REDIS_URL, DEFAULT_SECRET_KEY, Settings
from rag_eval_api.db import get_db_session
from rag_eval_api.main import create_app
from rag_eval_api.models import (
    AdapterConfig,
    AdapterKind,
    AdapterTestStatus,
    AuditEvent,
    Base,
    CandidateDataset,
    CandidateDatasetItem,
    CandidateDatasetStatus,
    CandidateDatasetVersion,
    CandidateGenerationConfig,
    CandidateItemEvidence,
    Document,
    DocumentChunk,
    DocumentParseStatus,
    DocumentVersion,
    IngestionJob,
    IngestionJobStatus,
    Membership,
    MembershipRole,
    ModelProviderConfig,
    Organization,
    Project,
)
from rag_eval_api.schemas.candidates import CandidateGenerationRequest
from rag_eval_api.schemas.experiments import ExperimentDraftRequest
from rag_eval_api.services.candidate_generation import (
    CandidateGenerationError,
    create_generation_job,
)
from rag_eval_api.services.candidate_worker import CandidateWorker
from rag_eval_api.services.experiment_validation import (
    ExperimentDraftValidationError,
    validate_experiment_draft,
)
from rag_eval_api.storage.protocol import StoredBlob

EDITOR_ID = UUID("00000000-0000-0000-0000-000000000201")
VIEWER_ID = UUID("00000000-0000-0000-0000-000000000202")
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000203")


class OversizedRequestBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield (
            b'--untrusted\r\nContent-Disposition: form-data; name="file"; '
            b'filename="payload.md"\r\nContent-Type: text/markdown\r\n\r\nok'
        )
        yield b"y" * 200


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
            Membership(organization=organization, user_id=ADMIN_ID, role=MembershipRole.admin),
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
        max_request_body_bytes=256,
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


def upload_version(
    client: httpx.AsyncClient,
    project_id: UUID,
    document_id: UUID,
    *,
    key: str,
    filename: str = "handbook.md",
    content: bytes = b"# Handbook v2\n",
) -> httpx.Response:
    return client.post(
        f"/api/projects/{project_id}/documents/{document_id}/versions",
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
        assert (
            audit.metadata_json["idempotency_key_sha256"] == hashlib.sha256(b"upload-1").hexdigest()
        )
        assert "idempotency_key" not in audit.metadata_json


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
        ("empty.md", b"", 422, "validation_error"),
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


@pytest.mark.asyncio
async def test_request_body_limit_rejects_chunked_body_before_multipart_parsing(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, _, blob_store = document_api_environment
    set_actor(EDITOR_ID)

    response = await client.post(
        f"/api/projects/{seed.project_id}/documents",
        headers={
            "Content-Type": "multipart/form-data; boundary=untrusted",
            "Idempotency-Key": "chunked-too-large",
        },
        content=OversizedRequestBody(),
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "size_exceeded",
            "message": "Request body exceeds the configured size limit.",
        }
    }
    assert blob_store.calls == 0


@pytest.mark.asyncio
async def test_database_commit_failure_removes_published_blob(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, seed, set_actor, _, blob_store = document_api_environment
    set_actor(EDITOR_ID)

    async def fail_commit(session: AsyncSession) -> None:
        del session
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)

    response = await upload(client, seed.project_id, key="commit-failure")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_server_error"
    assert blob_store.blobs == {}


@pytest.mark.asyncio
async def test_viewer_can_list_document_detail_and_versions_with_opaque_pagination(
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
    uploaded = await upload(client, seed.project_id, key="read-document")
    second_uploaded = await upload(
        client, seed.project_id, key="read-document-2", content=b"# Second document\n"
    )
    assert uploaded.status_code == 202
    document_id = uploaded.json()["document"]["id"]
    version_id = uploaded.json()["document_version"]["id"]
    set_actor(VIEWER_ID)

    listing = await client.get(
        f"/api/projects/{seed.project_id}/documents",
        params={"page_size": 1},
    )
    next_page = await client.get(
        f"/api/projects/{seed.project_id}/documents",
        params={"page_size": 1, "cursor": listing.json()["next_cursor"]},
    )
    detail = await client.get(f"/api/projects/{seed.project_id}/documents/{document_id}")
    versions = await client.get(f"/api/projects/{seed.project_id}/documents/{document_id}/versions")
    version = await client.get(
        f"/api/projects/{seed.project_id}/documents/{document_id}/versions/{version_id}"
    )

    assert (
        listing.status_code
        == detail.status_code
        == versions.status_code
        == version.status_code
        == 200
    )
    assert listing.json()["next_cursor"] is not None
    assert listing.json()["summary"]["total"] == 2
    assert next_page.status_code == 200
    assert next_page.json()["next_cursor"] is None
    assert {
        listing.json()["items"][0]["id"],
        next_page.json()["items"][0]["id"],
    } == {document_id, second_uploaded.json()["document"]["id"]}
    assert detail.json()["latest_version"]["id"] == version_id
    assert versions.json()["items"][0]["id"] == version_id
    assert version.json()["id"] == version_id
    assert blob_store.calls == 2
    async with session_factory() as session:
        assert len((await session.scalars(select(Document))).all()) == 2


@pytest.mark.asyncio
async def test_document_listing_filters_and_cross_project_access_fails_closed(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, _, _ = document_api_environment
    set_actor(EDITOR_ID)
    uploaded = await upload(client, seed.project_id, key="filter-document")
    document_id = uploaded.json()["document"]["id"]
    set_actor(VIEWER_ID)

    filtered = await client.get(
        f"/api/projects/{seed.project_id}/documents",
        params={"q": "handbook", "source_type": "markdown", "parse_status": "queued"},
    )
    denied = await client.get(f"/api/projects/{seed.other_project_id}/documents")
    hidden = await client.get(f"/api/projects/{seed.project_id}/documents/{uuid4()}/versions")

    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [document_id]
    assert denied.status_code == 403
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_retry_parse_creates_new_job_and_replay_is_idempotent(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    uploaded = await upload(client, seed.project_id, key="retry-source")
    body = uploaded.json()
    document_id = UUID(body["document"]["id"])
    version_id = UUID(body["document_version"]["id"])
    async with session_factory() as session:
        job = await session.scalar(
            select(IngestionJob).where(IngestionJob.document_version_id == version_id)
        )
        version = await session.get(DocumentVersion, version_id)
        assert job is not None and version is not None
        job.status = IngestionJobStatus.failed
        job.last_error_code = "parse_failed"
        version.parse_status = DocumentParseStatus.failed
        await session.commit()

    first = await client.post(
        f"/api/projects/{seed.project_id}/documents/{document_id}/versions/{version_id}/retry-parse",
        headers={"Idempotency-Key": "retry-1"},
    )
    replay = await client.post(
        f"/api/projects/{seed.project_id}/documents/{document_id}/versions/{version_id}/retry-parse",
        headers={"Idempotency-Key": "retry-1"},
    )

    assert first.status_code == replay.status_code == 202
    assert first.json() == replay.json()
    assert first.json()["id"] != body["ingestion_job"]["id"]
    async with session_factory() as session:
        jobs = list((await session.scalars(select(IngestionJob))).all())
        assert len(jobs) == 2
        assert len([job for job in jobs if job.status is IngestionJobStatus.queued]) == 1


@pytest.mark.asyncio
async def test_explicit_version_upload_preserves_history_and_updates_latest_pointer(
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
    first = await upload(client, seed.project_id, key="version-source", content=b"# v1\n")
    document_id = UUID(first.json()["document"]["id"])

    second = await upload_version(
        client,
        seed.project_id,
        document_id,
        key="version-2",
        content=b"# v2\n",
    )
    replay = await upload_version(
        client,
        seed.project_id,
        document_id,
        key="version-2",
        content=b"# v2\n",
    )
    duplicate = await upload_version(
        client,
        seed.project_id,
        document_id,
        key="version-duplicate",
        content=b"# v1\n",
    )

    assert second.status_code == replay.status_code == 202
    assert second.json() == replay.json()
    assert second.json()["document"]["id"] == str(document_id)
    assert second.json()["document_version"]["version_number"] == 2
    assert second.json()["document"]["latest_version_id"] == second.json()["document_version"]["id"]
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_document"
    assert blob_store.calls == 2
    async with session_factory() as session:
        versions = list(
            (
                await session.scalars(
                    select(DocumentVersion).where(DocumentVersion.document_id == document_id)
                )
            ).all()
        )
        assert {version.version_number for version in versions} == {1, 2}
        assert len((await session.scalars(select(IngestionJob))).all()) == 2


@pytest.mark.asyncio
async def test_job_query_and_cancel_are_project_scoped(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, _, _ = document_api_environment
    set_actor(EDITOR_ID)
    uploaded = await upload(client, seed.project_id, key="cancel-job")
    job_id = uploaded.json()["ingestion_job"]["id"]

    queried = await client.get(f"/api/projects/{seed.project_id}/ingestion-jobs/{job_id}")
    cancelled = await client.post(f"/api/projects/{seed.project_id}/ingestion-jobs/{job_id}/cancel")
    cross_project = await client.get(
        f"/api/projects/{seed.other_project_id}/ingestion-jobs/{job_id}"
    )

    assert queried.status_code == 200
    assert queried.json()["status"] == "queued"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cross_project.status_code == 403


@pytest.mark.asyncio
async def test_candidate_dataset_version_can_be_listed_and_published_when_empty(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    async with session_factory() as session:
        dataset = CandidateDataset(
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            name="回归评测集",
            status=CandidateDatasetStatus.draft,
        )
        session.add(dataset)
        await session.flush()
        version = CandidateDatasetVersion(
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            dataset_id=dataset.id,
            version_number=1,
            status=CandidateDatasetStatus.draft,
            created_by=EDITOR_ID,
        )
        session.add(version)
        await session.commit()
        dataset_id, version_id = dataset.id, version.id

    listed = await client.get(f"/api/projects/{seed.project_id}/candidate-datasets")
    versions = await client.get(
        f"/api/projects/{seed.project_id}/candidate-datasets/{dataset_id}/versions"
    )
    published = await client.post(
        f"/api/projects/{seed.project_id}/candidate-datasets/{dataset_id}/versions/{version_id}/publish"
    )

    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "回归评测集"
    assert versions.status_code == 200
    assert versions.json()[0]["version_number"] == 1
    assert published.status_code == 200
    assert published.json()["status"] == "published"


async def _mark_version_parsed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    version_id: UUID,
    organization_id: UUID,
    project_id: UUID,
) -> None:
    content = "The platform stores reproducible evaluation evidence."
    async with session_factory() as session:
        version = await session.get(DocumentVersion, version_id)
        assert version is not None
        version.parse_status = DocumentParseStatus.succeeded
        version.parser_version = "markdown-v1"
        session.add(
            DocumentChunk(
                organization_id=organization_id,
                project_id=project_id,
                document_version_id=version_id,
                ordinal=0,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                source_location={"paragraph": 0},
                character_count=len(content),
                token_count=8,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_generation_snapshot_is_idempotent_and_captures_chunk_hashes(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    uploaded = await upload(client, seed.project_id, key="generation-source")
    document_id = UUID(uploaded.json()["document"]["id"])
    version_id = UUID(uploaded.json()["document_version"]["id"])
    await _mark_version_parsed(
        session_factory,
        version_id=version_id,
        organization_id=seed.organization_id,
        project_id=seed.project_id,
    )
    payload = CandidateGenerationRequest(
        document_version_id=version_id,
        dataset_name="生成评测集",
        capability_version="candidate-generation-v1",
        prompt_version="prompt-v1",
        seed=7,
        randomness=0,
    )

    async with session_factory() as session:
        first_job, first_version = await create_generation_job(
            session,
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            actor_id=EDITOR_ID,
            document_id=document_id,
            idempotency_key="generation-key",
            payload=payload,
            provider_name="fake-test",
            model_name="fixture",
        )
        replay_job, replay_version = await create_generation_job(
            session,
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            actor_id=EDITOR_ID,
            document_id=document_id,
            idempotency_key="generation-key",
            payload=payload,
            provider_name="fake-test",
            model_name="fixture",
        )
        assert replay_job.id == first_job.id
        assert replay_version.id == first_version.id
        assert first_job.source_version_id == version_id
        assert first_job.generation_config_id is not None

        config = await session.get(CandidateGenerationConfig, first_job.generation_config_id)
        assert config is not None
        assert config.chunk_content_hashes == [
            hashlib.sha256(b"The platform stores reproducible evaluation evidence.").hexdigest()
        ]

        with pytest.raises(CandidateGenerationError, match="Idempotency-Key") as error:
            await create_generation_job(
                session,
                organization_id=seed.organization_id,
                project_id=seed.project_id,
                actor_id=EDITOR_ID,
                document_id=document_id,
                idempotency_key="generation-key",
                payload=payload.model_copy(update={"dataset_name": "另一个评测集"}),
                provider_name="fake-test",
                model_name="fixture",
            )
        assert error.value.code == "idempotency_conflict"


@pytest.mark.asyncio
async def test_candidate_worker_persists_items_and_evidence_with_fenced_attempt(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    uploaded = await upload(client, seed.project_id, key="worker-source")
    document_id = UUID(uploaded.json()["document"]["id"])
    version_id = UUID(uploaded.json()["document_version"]["id"])
    await _mark_version_parsed(
        session_factory,
        version_id=version_id,
        organization_id=seed.organization_id,
        project_id=seed.project_id,
    )
    async with session_factory() as session:
        job, dataset_version = await create_generation_job(
            session,
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            actor_id=EDITOR_ID,
            document_id=document_id,
            idempotency_key="worker-key",
            payload=CandidateGenerationRequest(
                document_version_id=version_id,
                dataset_name="Worker 评测集",
                capability_version="candidate-generation-v1",
                prompt_version="prompt-v1",
                seed=3,
                randomness=0,
            ),
            provider_name="fake-test",
            model_name="fixture",
        )

    worker = CandidateWorker(
        session_factory=session_factory,
        generator=FakeCandidateGenerator(),
        worker_id="candidate-test-worker",
        lease_ttl=timedelta(seconds=10),
    )
    result = await worker.process_batch(1)
    assert result.processed == 1
    assert result.succeeded == 1

    async with session_factory() as session:
        stored_job = await session.get(IngestionJob, job.id)
        assert stored_job is not None
        assert stored_job.status is IngestionJobStatus.succeeded
        assert stored_job.attempt_count == 1
        item = await session.scalar(
            select(CandidateDatasetItem).where(
                CandidateDatasetItem.dataset_version_id == dataset_version.id
            )
        )
        assert item is not None
        evidence = await session.scalar(
            select(CandidateItemEvidence).where(CandidateItemEvidence.item_id == item.id)
        )
        assert evidence is not None
        assert evidence.source_version_id == version_id


@pytest.mark.asyncio
async def test_candidate_generation_requires_configured_provider_before_creating_work(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    response = await client.post(
        f"/api/projects/{seed.project_id}/documents/{uuid4()}/generate-candidates",
        headers={"Idempotency-Key": "provider-not-configured"},
        json={
            "document_version_id": str(uuid4()),
            "dataset_name": "评测集",
            "capability_version": "candidate-generation-v1",
            "prompt_version": "prompt-v1",
            "randomness": 0,
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"
    async with session_factory() as session:
        assert (await session.scalars(select(IngestionJob))).all() == []


@pytest.mark.asyncio
async def test_editor_can_create_secret_free_adapter_configuration(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    response = await client.post(
        f"/api/projects/{seed.project_id}/adapters",
        json={
            "name": "本地 RAG",
            "kind": "http",
            "endpoint": "https://adapter.example.test",
            "credential_ref": "RAG_ADAPTER_TOKEN",
            "adapter_version": "adapter-v1",
            "trace_level": "minimal",
            "timeout_seconds": 5,
            "retry_count": 1,
            "enabled": False,
        },
    )

    assert response.status_code == 201
    assert response.json()["credential_ref"] == "RAG_ADAPTER_TOKEN"
    assert "token" not in response.json()
    listed = await client.get(f"/api/projects/{seed.project_id}/adapters")
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "本地 RAG"
    async with session_factory() as session:
        stored = await session.scalar(select(AdapterConfig))
        assert stored is not None
        assert stored.token_last4 is None


@pytest.mark.asyncio
async def test_adapter_crud_is_project_scoped_and_admin_delete_is_audited(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    created = await client.post(
        f"/api/projects/{seed.project_id}/adapters",
        json={
            "name": "可更新 Adapter",
            "kind": "http",
            "endpoint": "https://adapter.example.test",
            "adapter_version": "adapter-v1",
        },
    )
    assert created.status_code == 201
    adapter_id = created.json()["id"]

    updated = await client.patch(
        f"/api/projects/{seed.project_id}/adapters/{adapter_id}",
        json={"name": "已更新 Adapter", "timeout_seconds": 10},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "已更新 Adapter"
    fetched = await client.get(f"/api/projects/{seed.project_id}/adapters/{adapter_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "已更新 Adapter"

    set_actor(ADMIN_ID)
    deleted = await client.delete(f"/api/projects/{seed.project_id}/adapters/{adapter_id}")
    assert deleted.status_code == 204
    fetched_after_delete = await client.get(
        f"/api/projects/{seed.project_id}/adapters/{adapter_id}"
    )
    assert fetched_after_delete.status_code == 404
    async with session_factory() as session:
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "adapter.deleted",
                AuditEvent.resource_id == adapter_id,
            )
        )
        assert audit is not None


@pytest.mark.asyncio
async def test_adapter_connection_test_records_failure_without_leaking_credentials(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    created = await client.post(
        f"/api/projects/{seed.project_id}/adapters",
        json={
            "name": "缺少凭据 Adapter",
            "kind": "http",
            "endpoint": "https://adapter.example.test",
            "credential_ref": "MISSING_RAG_ADAPTER_TOKEN",
            "adapter_version": "adapter-v1",
        },
    )
    adapter_id = created.json()["id"]
    tested = await client.post(
        f"/api/projects/{seed.project_id}/adapters/{adapter_id}/test"
    )
    assert tested.status_code == 503
    assert tested.json()["error"]["code"] == "adapter_credentials_unavailable"
    assert "MISSING_RAG_ADAPTER_TOKEN" not in tested.text
    async with session_factory() as session:
        stored = await session.get(AdapterConfig, UUID(adapter_id))
        assert stored is not None
        assert stored.last_test_status.value == "failed"


@pytest.mark.asyncio
async def test_editor_can_create_secret_free_model_provider_configuration(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    response = await client.post(
        f"/api/projects/{seed.project_id}/model-providers",
        json={
            "name": "模型服务",
            "endpoint": "https://model.example.test",
            "credential_ref": "MODEL_API_TOKEN",
            "model_name": "model-a",
            "timeout_seconds": 15,
            "enabled": False,
        },
    )

    assert response.status_code == 201
    assert response.json()["credential_ref"] == "MODEL_API_TOKEN"
    listed = await client.get(f"/api/projects/{seed.project_id}/model-providers")
    assert listed.status_code == 200
    assert listed.json()[0]["model_name"] == "model-a"
    async with session_factory() as session:
        assert (
            await session.scalar(select(ModelProviderConfig))
        ).credential_ref == "MODEL_API_TOKEN"


@pytest.mark.asyncio
async def test_model_provider_crud_and_connection_failure_are_tenant_scoped(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, _ = document_api_environment
    set_actor(EDITOR_ID)
    created = await client.post(
        f"/api/projects/{seed.project_id}/model-providers",
        json={
            "name": "待测试模型",
            "endpoint": "https://model.example.test",
            "credential_ref": "MISSING_MODEL_PROVIDER_TOKEN",
            "model_name": "model-a",
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]
    updated = await client.patch(
        f"/api/projects/{seed.project_id}/model-providers/{provider_id}",
        json={"model_name": "model-b"},
    )
    assert updated.status_code == 200
    assert updated.json()["model_name"] == "model-b"
    tested = await client.post(
        f"/api/projects/{seed.project_id}/model-providers/{provider_id}/test"
    )
    assert tested.status_code == 503
    assert tested.json()["error"]["code"] == "provider_credentials_unavailable"
    assert "MISSING_MODEL_PROVIDER_TOKEN" not in tested.text
    async with session_factory() as session:
        stored = await session.get(ModelProviderConfig, UUID(provider_id))
        assert stored is not None
        assert stored.last_test_status.value == "failed"

    set_actor(ADMIN_ID)
    deleted = await client.delete(
        f"/api/projects/{seed.project_id}/model-providers/{provider_id}"
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_experiment_draft_requires_published_dataset_and_available_dependencies(
    document_api_environment: tuple[
        httpx.AsyncClient,
        Seed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        FakeBlobStore,
    ],
) -> None:
    _, seed, _, session_factory, _ = document_api_environment
    async with session_factory() as session:
        dataset = CandidateDataset(
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            name="实验评测集",
            status=CandidateDatasetStatus.draft,
        )
        version = CandidateDatasetVersion(
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            dataset=dataset,
            version_number=1,
            status=CandidateDatasetStatus.draft,
            item_count=2,
            created_by=EDITOR_ID,
        )
        adapter = AdapterConfig(
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            name="实验 Adapter",
            kind=AdapterKind.http,
            endpoint="https://adapter.example.test",
            adapter_version="adapter-v1",
            trace_level="minimal",
            timeout_seconds=30,
            retry_count=0,
            enabled=False,
            last_test_status=AdapterTestStatus.never,
        )
        provider = ModelProviderConfig(
            organization_id=seed.organization_id,
            project_id=seed.project_id,
            name="实验模型",
            endpoint="https://model.example.test",
            credential_ref="MODEL_TOKEN",
            model_name="model-a",
            timeout_seconds=30,
            enabled=True,
        )
        session.add_all([dataset, version, adapter, provider])
        await session.commit()
        project = await session.get(Project, seed.project_id)
        membership = await session.scalar(
            select(Membership).where(
                Membership.project_id == seed.project_id, Membership.user_id == EDITOR_ID
            )
        )
        assert project is not None and membership is not None
        access = ProjectAccess(
            project=project,
            membership=membership,
            actor=RequestActor(user_id=EDITOR_ID, organization_id=seed.organization_id),
        )
        payload = ExperimentDraftRequest(
            name="首次实验",
            dataset_version_id=version.id,
            adapter_config_id=adapter.id,
            model_provider_id=provider.id,
            metric_versions={"retrieval": "v1"},
            random_seed=42,
        )
        with pytest.raises(ExperimentDraftValidationError, match="published") as unpublished:
            await validate_experiment_draft(session, access, payload)
        assert unpublished.value.code == "dataset_version_unpublished"

        version.status = CandidateDatasetStatus.published
        await session.flush()
        with pytest.raises(ExperimentDraftValidationError, match="Adapter") as unavailable:
            await validate_experiment_draft(session, access, payload)
        assert unavailable.value.code == "adapter_unavailable"

        adapter.enabled = True
        adapter.last_test_status = AdapterTestStatus.succeeded
        validated = await validate_experiment_draft(session, access, payload)
        assert validated.dataset_item_count == 2
        assert validated.adapter_version == "adapter-v1"
        assert validated.random_seed == 42
