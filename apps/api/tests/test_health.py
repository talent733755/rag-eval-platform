from fastapi.testclient import TestClient

from conftest import FakeDatabaseSession, FakeRedisClient


def test_liveness_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_does_not_contact_dependencies(
    client: TestClient,
    db_session: FakeDatabaseSession,
    redis_client: FakeRedisClient,
) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert db_session.execute_calls == 0
    assert redis_client.ping_calls == 0


def test_readiness_reports_database_and_redis_dependencies(
    client: TestClient,
    db_session: FakeDatabaseSession,
    redis_client: FakeRedisClient,
) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "dependencies": {"database": "ok", "redis": "ok"},
    }
    assert db_session.execute_calls == 1
    assert redis_client.ping_calls == 1


def test_readiness_returns_safe_503_when_database_fails(
    redis_client: FakeRedisClient,
) -> None:
    from rag_eval_api.db import get_db_session, get_redis_client
    from rag_eval_api.main import app

    failing_db = FakeDatabaseSession(
        error=RuntimeError("postgresql://user:password@example.invalid/db")
    )
    app.dependency_overrides[get_db_session] = lambda: failing_db
    app.dependency_overrides[get_redis_client] = lambda: redis_client
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "dependencies": {"database": "error", "redis": "ok"},
    }
    assert "password" not in response.text
    assert "postgresql://" not in response.text


def test_readiness_returns_safe_503_when_redis_fails(
    db_session: FakeDatabaseSession,
) -> None:
    from rag_eval_api.db import get_db_session, get_redis_client
    from rag_eval_api.main import app

    failing_redis = FakeRedisClient(error=RuntimeError("redis://:secret@example.invalid"))
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_redis_client] = lambda: failing_redis
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "dependencies": {"database": "ok", "redis": "error"},
    }
    assert "secret" not in response.text
    assert "redis://" not in response.text


def test_production_settings_reject_default_secret() -> None:
    from rag_eval_api.config import Settings

    try:
        Settings(APP_ENV="production", SECRET_KEY="development-only-secret")
    except ValueError as error:
        assert "SECRET_KEY" in str(error)
    else:
        raise AssertionError("production settings accepted an unsafe secret")
