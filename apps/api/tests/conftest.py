from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeDatabaseSession:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.execute_calls = 0

    async def execute(self, statement: Any) -> None:
        del statement
        self.execute_calls += 1
        if self.error is not None:
            raise self.error


class FakeRedisClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.ping_calls = 0

    async def ping(self) -> bool:
        self.ping_calls += 1
        if self.error is not None:
            raise self.error
        return True


@pytest.fixture
def db_session() -> FakeDatabaseSession:
    return FakeDatabaseSession()


@pytest.fixture
def redis_client() -> FakeRedisClient:
    return FakeRedisClient()


@pytest.fixture
def app() -> Iterator[FastAPI]:
    from rag_eval_api.config import (
        DEFAULT_DATABASE_URL,
        DEFAULT_REDIS_URL,
        DEFAULT_SECRET_KEY,
        Settings,
    )
    from rag_eval_api.main import create_app

    settings = Settings.model_validate(
        {
            "DATABASE_URL": DEFAULT_DATABASE_URL,
            "REDIS_URL": DEFAULT_REDIS_URL,
            "APP_ENV": "development",
            "CORS_ORIGINS": ["http://localhost:3000"],
            "LOG_LEVEL": "INFO",
            "SECRET_KEY": DEFAULT_SECRET_KEY,
            "_env_file": None,
        }
    )
    application = create_app(settings=settings)
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(
    app: FastAPI,
    db_session: FakeDatabaseSession,
    redis_client: FakeRedisClient,
) -> Iterator[TestClient]:
    from rag_eval_api.db import get_db_session, get_redis_client

    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_factory(app: FastAPI) -> Iterator[Any]:
    from rag_eval_api.db import get_db_session, get_redis_client

    def factory(db_session: Any, redis_client: Any) -> TestClient:
        app.dependency_overrides[get_db_session] = lambda: db_session
        app.dependency_overrides[get_redis_client] = lambda: redis_client
        return TestClient(app)

    yield factory
