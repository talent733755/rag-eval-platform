from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from rag_eval_api.config import (
    DEFAULT_DATABASE_URL,
    DEFAULT_REDIS_URL,
    DEFAULT_SECRET_KEY,
    Settings,
)
from rag_eval_api.main import create_app


class RecordingBlobStore:
    instances: list[RecordingBlobStore] = []

    def __init__(self, root: str, *, max_bytes: int) -> None:
        self.root = root
        self.max_bytes = max_bytes
        self.closed = False
        self.__class__.instances.append(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def lifecycle_settings() -> Settings:
    return Settings(
        database_url=DEFAULT_DATABASE_URL,
        redis_url=DEFAULT_REDIS_URL,
        app_env="development",
        cors_origins=["http://localhost:3003"],
        log_level="INFO",
        secret_key=SecretStr(DEFAULT_SECRET_KEY),
        _env_file=None,  # type: ignore[call-arg]
    )


def test_create_app_assembles_and_closes_default_blob_store(
    monkeypatch: pytest.MonkeyPatch,
    lifecycle_settings: Settings,
) -> None:
    from rag_eval_api import main

    RecordingBlobStore.instances.clear()
    monkeypatch.setattr(main, "LocalBlobStore", RecordingBlobStore)
    application = create_app(settings=lifecycle_settings)

    with TestClient(application):
        assert len(RecordingBlobStore.instances) == 1
        store = RecordingBlobStore.instances[0]
        assert store.root == lifecycle_settings.blob_root
        assert store.max_bytes == lifecycle_settings.max_upload_bytes

    assert store.closed
