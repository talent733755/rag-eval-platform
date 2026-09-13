from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.config import DEFAULT_REDIS_URL, DEFAULT_SECRET_KEY, Settings
from rag_eval_api.db import get_db_session
from rag_eval_api.models import Base, Membership, MembershipRole, Organization, Project

ACTOR_ID = UUID("00000000-0000-4000-8000-000000000001")


@pytest_asyncio.fixture
async def authentication_environment() -> AsyncIterator[
    tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]]
]:
    from rag_eval_api.main import create_app

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

    settings = Settings(
        database_url="postgresql+asyncpg://rag_eval:change-me@localhost:5432/rag_eval",
        redis_url=DEFAULT_REDIS_URL,
        app_env="development",
        dev_actor_id=ACTOR_ID,
        cors_origins=["http://localhost:3003"],
        secret_key=DEFAULT_SECRET_KEY,
        _env_file=None,  # type: ignore[call-arg]
    )
    application = create_app(settings=settings)

    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_db_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            yield application, client, session_factory
    finally:
        application.dependency_overrides.clear()
        await application.state.db_engine.dispose()
        await application.state.redis_client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_development_actor_is_resolved_from_unique_membership(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    _, client, session_factory = authentication_environment
    async with session_factory() as session:
        organization = Organization(name="Development", slug="development")
        project = Project(name="Demo project", slug="demo", organization=organization)
        membership = Membership(
            organization=organization,
            project=project,
            user_id=ACTOR_ID,
            role=MembershipRole.admin,
        )
        session.add_all([organization, project, membership])
        await session.commit()

    response = await client.get("/api/projects")

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "demo"


@pytest.mark.asyncio
async def test_development_actor_requires_a_membership(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    _, client, _ = authentication_environment

    response = await client.get("/api/projects")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "development_actor_not_provisioned",
            "message": "Development actor is not provisioned in any organization.",
        }
    }


@pytest.mark.asyncio
async def test_development_actor_rejects_multiple_organizations(
    authentication_environment: tuple[FastAPI, httpx.AsyncClient, async_sessionmaker[AsyncSession]],
) -> None:
    _, client, session_factory = authentication_environment
    async with session_factory() as session:
        first_organization = Organization(name="First", slug="first")
        second_organization = Organization(name="Second", slug="second")
        first_project = Project(name="First project", slug="first", organization=first_organization)
        second_project = Project(
            name="Second project", slug="second", organization=second_organization
        )
        session.add_all(
            [
                first_organization,
                second_organization,
                first_project,
                second_project,
                Membership(
                    organization=first_organization,
                    project=first_project,
                    user_id=ACTOR_ID,
                    role=MembershipRole.admin,
                ),
                Membership(
                    organization=second_organization,
                    project=second_project,
                    user_id=ACTOR_ID,
                    role=MembershipRole.admin,
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/projects")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "development_actor_ambiguous",
            "message": "Development actor belongs to multiple organizations.",
        }
    }


def test_empty_dev_actor_id_is_treated_as_unset() -> None:
    settings = Settings.model_validate(
        {
            "APP_ENV": "development",
            "DEV_ACTOR_ID": "",
            "_env_file": None,
        }
    )

    assert settings.dev_actor_id is None
