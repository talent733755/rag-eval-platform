import asyncio
import json
import logging
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import FakeDatabaseSession, FakeRedisClient


def test_liveness_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_exposes_the_versioned_project_contract(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert document["openapi"].startswith("3.")
    assert document["info"]["version"] == "0.1.0"
    assert document["paths"]["/api/projects"]["get"]["operationId"] == (
        "list_projects_api_projects_get"
    )
    assert document["paths"]["/api/projects/{project_id}/members"]["get"]["responses"]["200"]


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
    client_factory: object,
    redis_client: FakeRedisClient,
) -> None:
    from rag_eval_api.db import get_db_session, get_redis_client

    failing_db = FakeDatabaseSession(
        error=RuntimeError("postgresql://user:password@example.invalid/db")
    )
    del get_db_session, get_redis_client
    with client_factory(failing_db, redis_client) as test_client:  # type: ignore[operator]
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "dependencies": {"database": "error", "redis": "ok"},
    }
    assert "password" not in response.text
    assert "postgresql://" not in response.text


def test_readiness_returns_safe_503_when_redis_fails(
    client_factory: object,
    db_session: FakeDatabaseSession,
) -> None:
    failing_redis = FakeRedisClient(error=RuntimeError("redis://:secret@example.invalid"))
    with client_factory(db_session, failing_redis) as test_client:  # type: ignore[operator]
        response = test_client.get("/health/ready")

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
        # Isolate from the repository .env so only the secret-key guard is exercised;
        # DEV_ACTOR_ID is unset to keep the production env-var guard from firing first.
        Settings.model_validate(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "development-only-secret",
                "DEV_ACTOR_ID": None,
                "_env_file": None,
            }
        )
    except ValueError as error:
        assert "SECRET_KEY" in str(error)
    else:
        raise AssertionError("production settings accepted an unsafe secret")


def test_settings_accept_comma_separated_cors_origins() -> None:
    from rag_eval_api.config import Settings

    settings = Settings.model_validate(
        {
            "CORS_ORIGINS": "http://localhost:3003, https://example.com",
            "_env_file": None,
        }
    )

    assert settings.cors_origins == ["http://localhost:3003", "https://example.com"]


def test_settings_reject_invalid_log_level() -> None:
    from rag_eval_api.config import Settings

    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings.model_validate({"LOG_LEVEL": "verbose", "_env_file": None})


def test_settings_normalize_log_level() -> None:
    from rag_eval_api.config import Settings

    settings = Settings.model_validate({"LOG_LEVEL": "warning", "_env_file": None})

    assert settings.log_level == "WARNING"


def test_settings_reject_invalid_connection_schemes() -> None:
    from rag_eval_api.config import Settings

    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings.model_validate({"DATABASE_URL": "mysql://localhost/db", "_env_file": None})
    with pytest.raises(ValueError, match="REDIS_URL"):
        Settings.model_validate({"REDIS_URL": "http://localhost:6379", "_env_file": None})


def test_settings_uses_repository_root_env_file() -> None:
    from rag_eval_api.config import repository_env_file

    expected_root = Path(__file__).resolve().parents[3]

    assert repository_env_file() == expected_root / ".env"


class StalledDatabaseSession:
    async def execute(self, statement: object) -> None:
        del statement
        await asyncio.Event().wait()


class StalledRedisClient:
    async def ping(self) -> bool:
        await asyncio.Event().wait()
        return True


def test_readiness_times_out_stalled_database(
    client_factory: object, redis_client: FakeRedisClient
) -> None:
    from rag_eval_api.main import HEALTH_CHECK_TIMEOUT_SECONDS

    started = time.monotonic()
    with client_factory(StalledDatabaseSession(), redis_client) as test_client:  # type: ignore[operator]
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"] == {"database": "error", "redis": "ok"}
    assert time.monotonic() - started < HEALTH_CHECK_TIMEOUT_SECONDS + 1


def test_readiness_times_out_stalled_redis(
    client_factory: object, db_session: FakeDatabaseSession
) -> None:
    from rag_eval_api.main import HEALTH_CHECK_TIMEOUT_SECONDS

    started = time.monotonic()
    with client_factory(db_session, StalledRedisClient()) as test_client:  # type: ignore[operator]
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"] == {"database": "ok", "redis": "error"}
    assert time.monotonic() - started < HEALTH_CHECK_TIMEOUT_SECONDS + 1


def test_log_formatter_emits_structured_fields() -> None:
    from rag_eval_api.main import JsonLogFormatter

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "request.completed", (), None)
    setattr(record, "event", "request.completed")
    setattr(record, "method", "GET")
    setattr(record, "path", "/health/live")
    setattr(record, "status_code", 200)

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["event"] == "request.completed"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200


def test_log_formatter_emits_worker_and_trace_fields() -> None:
    from rag_eval_api.main import JsonLogFormatter

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "worker.lease_lost", (), None)
    setattr(record, "event", "worker.lease_lost")
    setattr(record, "job_id", "job-1")
    setattr(record, "run_id", "run-1")
    setattr(record, "run_item_id", "item-1")
    setattr(record, "attempt_number", 2)
    setattr(record, "lease_id", "lease-1")
    setattr(record, "fencing_token", 7)
    setattr(record, "trace_id", "trace-1")
    setattr(record, "project_id", "project-1")
    setattr(record, "error_code", "adapter_error")

    payload = json.loads(JsonLogFormatter().format(record))

    for key in (
        "job_id",
        "run_id",
        "run_item_id",
        "attempt_number",
        "lease_id",
        "fencing_token",
        "trace_id",
        "project_id",
        "error_code",
    ):
        assert payload[key] is not None, key


def test_log_formatter_redacts_credentials_in_freeform_fields() -> None:
    from rag_eval_api.main import JsonLogFormatter

    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "worker.failed", (), None)
    setattr(record, "event", "worker.failed")
    setattr(record, "error_message", "request to https://user:secret@api.example failed token=abc")
    setattr(record, "job_id", "job-1")

    payload = json.loads(JsonLogFormatter().format(record))

    assert "secret" not in payload["error_message"]
    assert "token=abc" not in payload["error_message"]


def test_unhandled_failure_logs_sanitized_context_and_completion(
    app: object, caplog: pytest.LogCaptureFixture
) -> None:
    from fastapi import FastAPI

    from rag_eval_api.main import logger

    application = app
    assert isinstance(application, FastAPI)

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("password=hunter2 postgres://user:secret@example.invalid/db")

    caplog.set_level(logging.INFO, logger=logger.name)
    logger.propagate = True
    try:
        with TestClient(application, raise_server_exceptions=False) as test_client:
            response = test_client.get("/boom")
    finally:
        logger.propagate = False

    assert response.status_code == 500
    messages = " ".join(
        " ".join(
            [
                record.getMessage(),
                str(getattr(record, "exception_type", "")),
                str(getattr(record, "exception_message", "")),
            ]
        )
        for record in caplog.records
    )
    assert "request.completed" in messages
    assert "RuntimeError" in messages
    assert "hunter2" not in messages
    assert "postgres://user:secret" not in messages


@pytest.mark.asyncio
async def test_resource_cleanup_closes_redis_when_database_dispose_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fastapi import FastAPI

    from rag_eval_api.db import close_resources
    from rag_eval_api.main import JsonLogFormatter, logger

    class FailingEngine:
        async def dispose(self) -> None:
            raise RuntimeError("postgres://user:secret@example.invalid/db")

    class TrackableRedis:
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    application = FastAPI()
    redis_client = TrackableRedis()
    application.state.db_engine = FailingEngine()
    application.state.redis_client = redis_client

    caplog.set_level(logging.ERROR, logger=logger.name)
    logger.propagate = True
    try:
        await close_resources(application)
    finally:
        logger.propagate = False

    assert redis_client.closed
    cleanup_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "resource.cleanup.failed"
    ]
    assert cleanup_records
    assert all(record.name == logger.name for record in cleanup_records)
    assert any(isinstance(handler.formatter, JsonLogFormatter) for handler in logger.handlers)
    assert "secret" not in str(getattr(cleanup_records[0], "exception_message", ""))


def test_worker_entrypoint_configures_json_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    import rag_eval_api.worker as worker_module
    from rag_eval_api.main import JsonLogFormatter

    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: worker_module.Settings(_env_file=None, worker_enabled=False),
    )

    result = worker_module.main(["--once"])

    assert result == 0
    package_logger = logging.getLogger("rag_eval_api")
    assert any(
        isinstance(handler.formatter, JsonLogFormatter) for handler in package_logger.handlers
    )
    assert worker_module.LOGGER.name.startswith(package_logger.name)
