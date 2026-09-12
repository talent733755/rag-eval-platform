"""PostgreSQL-backed HTTP tests for document ingestion."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_eval_api.auth.context import RequestActor, get_current_actor
from rag_eval_api.config import DEFAULT_REDIS_URL, DEFAULT_SECRET_KEY, Settings
from rag_eval_api.db import get_db_session
from rag_eval_api.main import create_app
from rag_eval_api.models import (
    Document,
    DocumentVersion,
    Membership,
    MembershipRole,
    Organization,
    Project,
)
from rag_eval_api.storage.local import LocalBlobStore

EDITOR_ID = UUID("00000000-0000-0000-0000-000000000301")


@dataclass(frozen=True)
class IntegrationSeed:
    organization_id: UUID
    project_id: UUID


@pytest_asyncio.fixture
async def document_api_postgres_environment(
    tmp_path: Path,
) -> AsyncIterator[
    tuple[
        httpx.AsyncClient,
        IntegrationSeed,
        async_sessionmaker[AsyncSession],
        LocalBlobStore,
    ]
]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    settings = Settings(
        database_url=database_url,
        redis_url=DEFAULT_REDIS_URL,
        app_env="development",
        cors_origins=["http://localhost:3000"],
        log_level="INFO",
        secret_key=SecretStr(DEFAULT_SECRET_KEY),
        max_upload_bytes=1024,
        max_request_body_bytes=2048,
        _env_file=None,  # type: ignore[call-arg]
    )
    blob_store = LocalBlobStore(tmp_path / "blobs", max_bytes=settings.max_upload_bytes)
    application = create_app(settings=settings, blob_store=blob_store)
    session_factory = application.state.db_session_factory
    organization = Organization(name="HTTP integration org", slug="http-integration-org")
    project = Project(
        name="HTTP integration project",
        slug="http-integration-project",
        organization=organization,
    )
    project.memberships.append(
        Membership(organization=organization, user_id=EDITOR_ID, role=MembershipRole.editor)
    )
    async with session_factory() as session:
        session.add_all([organization, project])
        await session.commit()
        seed = IntegrationSeed(
            organization_id=organization.id,
            project_id=project.id,
        )

    application.dependency_overrides[get_current_actor] = lambda: RequestActor(
        user_id=EDITOR_ID,
        organization_id=seed.organization_id,
    )

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            yield client, seed, session_factory, blob_store
    finally:
        application.dependency_overrides.clear()
        await application.state.db_engine.dispose()
        await application.state.redis_client.aclose()
        blob_store.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_concurrent_version_upload_preserves_both_commits_and_no_orphan_blob(
    document_api_postgres_environment: tuple[
        httpx.AsyncClient,
        IntegrationSeed,
        async_sessionmaker[AsyncSession],
        LocalBlobStore,
    ],
) -> None:
    client, seed, session_factory, blob_store = document_api_postgres_environment
    initial = await client.post(
        f"/api/projects/{seed.project_id}/documents",
        headers={"Idempotency-Key": "integration-initial"},
        files={"file": ("handbook.md", b"# v1\n", "text/markdown")},
    )
    assert initial.status_code == 202
    document_id = initial.json()["document"]["id"]

    async def upload_version(key: str, content: bytes) -> httpx.Response:
        return await client.post(
            f"/api/projects/{seed.project_id}/documents/{document_id}/versions",
            headers={"Idempotency-Key": key},
            files={"file": ("handbook.md", content, "text/markdown")},
        )

    responses = await asyncio.gather(
        upload_version("integration-version-a", b"# v2-a\n"),
        upload_version("integration-version-b", b"# v2-b\n"),
    )

    assert [response.status_code for response in responses] == [202, 202]
    assert sorted(
        response.json()["document_version"]["version_number"] for response in responses
    ) == [
        2,
        3,
    ]

    async with session_factory() as session:
        document = await session.scalar(select(Document).where(Document.id == document_id))
        versions = list(
            (
                await session.scalars(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == document_id)
                    .order_by(DocumentVersion.version_number)
                )
            ).all()
        )
    assert document is not None
    assert document.latest_version_id == versions[-1].id
    assert [version.version_number for version in versions] == [1, 2, 3]
    assert all(blob_store.exists(version.storage_key) for version in versions)
    assert len([path for path in blob_store.root.rglob("*") if path.is_file()]) == 3
