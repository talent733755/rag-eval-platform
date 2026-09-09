from collections.abc import Iterator
from typing import Any

import pytest
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
def client(
    db_session: FakeDatabaseSession,
    redis_client: FakeRedisClient,
) -> Iterator[TestClient]:
    from rag_eval_api.db import get_db_session, get_redis_client
    from rag_eval_api.main import app

    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
