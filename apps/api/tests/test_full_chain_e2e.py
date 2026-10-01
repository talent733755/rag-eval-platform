"""Deterministic end-to-end fixture: upload → parse → candidates → review → publish → experiment → metrics → trace → regression set.

No external providers or real user data are used: the candidate provider is the
built-in deterministic ``FakeCandidateGenerator`` and the experiment adapter is a
scripted in-process stub.
"""

from __future__ import annotations

import hashlib
import io
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import timedelta
from io import BufferedReader
from typing import Any, BinaryIO
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.adapters.errors import AdapterError
from rag_eval_api.adapters.protocol import AdapterResponse
from rag_eval_api.auth.context import RequestActor, get_current_actor
from rag_eval_api.candidates.fake import FakeCandidateGenerator
from rag_eval_api.config import DEFAULT_REDIS_URL, DEFAULT_SECRET_KEY, Settings
from rag_eval_api.db import get_db_session
from rag_eval_api.main import create_app
from rag_eval_api.models import Base, Membership, MembershipRole, Organization, Project
from rag_eval_api.services.candidate_worker import CandidateWorker
from rag_eval_api.services.experiment_worker import ExperimentWorker
from rag_eval_api.storage.protocol import StoredBlob

EDITOR_ID = UUID("00000000-0000-0000-0000-000000000901")
ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000910")


class WorkingBlobStore:
    """In-memory blob store that supports put/open for worker-driven parsing."""

    blobs: dict[str, bytes]
    calls: int

    def __init__(self) -> None:
        self.blobs = {}
        self.calls = 0

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
        key = f"e2e/{uuid4()}"
        self.blobs[key] = data
        return StoredBlob(storage_key=key, byte_size=len(data), sha256=digest)

    def open(self, storage_key: str) -> AbstractContextManager[BufferedReader]:
        blobs = self.blobs

        class _BlobContext(AbstractContextManager[BufferedReader]):
            def __enter__(self) -> BufferedReader:
                return io.BytesIO(blobs[storage_key])

            def __exit__(self, *exc: object) -> None:
                return None

        return _BlobContext()

    def exists(self, storage_key: str) -> bool:
        return storage_key in self.blobs

    def delete(self, storage_key: str) -> None:
        self.blobs.pop(storage_key, None)


class ScriptedAdapter:
    """Deterministic adapter: answer "答案" with a trace, bounded latency."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def run(self, request: Any) -> AdapterResponse:
        if self.fail:
            raise AdapterError("upstream_error", "Upstream failed.", retryable=False)
        return AdapterResponse(
            request_id=request.request_id,
            answer=f"答案：{request.question}",
            usage={"latency_ms": 4, "input_tokens": 12, "output_tokens": 8},
            trace={
                "trace_id": f"trace-{request.request_id}",
                "level": "minimal",
                # This happy-path fake does not expose structured retrieval evidence;
                # the platform must not attribute a retrieval miss in that case.
                "stages": {"generate": {"text": "answer"}},
            },
        )


class OpenAICompatibleFakeGenerator:
    """Deterministic generator whose provider name matches the route's configured provider."""

    def __init__(self) -> None:
        self._delegate = FakeCandidateGenerator()

    def generate(
        self,
        request: Any,
        cancel_token: object | None = None,
    ) -> Any:
        result = self._delegate.generate(request, cancel_token)
        return type(result)(
            capability_version=result.capability_version,
            provider_name="openai-compatible",
            items=result.items,
            provenance=result.provenance,
        )


@dataclass(frozen=True)
class E2ESeed:
    organization_id: UUID
    project_id: UUID


@pytest_asyncio.fixture
async def e2e_environment() -> AsyncIterator[
    tuple[
        httpx.AsyncClient,
        E2ESeed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        WorkingBlobStore,
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

    organization = Organization(id=ORGANIZATION_ID, name="E2E Org", slug="e2e-org")
    project = Project(name="E2E Project", slug="e2e-project", organization=organization)
    project.memberships.append(
        Membership(organization=organization, user_id=EDITOR_ID, role=MembershipRole.editor)
    )
    async with session_factory() as session:
        session.add_all([organization, project])
        await session.commit()
        seed = E2ESeed(organization_id=organization.id, project_id=project.id)

    settings = Settings(
        database_url="postgresql+asyncpg://rag_eval:change-me@localhost:5432/rag_eval",
        redis_url=DEFAULT_REDIS_URL,
        app_env="development",
        cors_origins=["http://localhost:3003"],
        log_level="INFO",
        secret_key=SecretStr(DEFAULT_SECRET_KEY),
        provider_base_url="https://provider.example.test/v1",
        provider_api_key=SecretStr("test-key"),
        provider_allowed_hosts=["provider.example.test"],
        provider_allowed_ports=[443],
        _env_file=None,  # type: ignore[call-arg]
    )
    application = create_app(settings=settings)
    blob_store = WorkingBlobStore()
    application.state.blob_store = blob_store
    current_actor = RequestActor(user_id=EDITOR_ID, organization_id=seed.organization_id)
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


@pytest.mark.asyncio
async def test_deterministic_full_chain_upload_to_regression_set(
    e2e_environment: tuple[
        httpx.AsyncClient,
        E2ESeed,
        Callable[[UUID], None],
        async_sessionmaker[AsyncSession],
        WorkingBlobStore,
    ],
) -> None:
    client, seed, set_actor, session_factory, blob_store = e2e_environment
    set_actor(EDITOR_ID)

    # 1. Upload a markdown document.
    content = b"# Guide\n\nThe platform stores reproducible evaluation evidence.\n"
    uploaded = await client.post(
        f"/api/projects/{seed.project_id}/documents",
        headers={"Idempotency-Key": "e2e-upload-1"},
        files={"file": ("guide.md", content, "text/markdown")},
    )
    assert uploaded.status_code == 202
    document_id = UUID(uploaded.json()["document"]["id"])
    version_id = UUID(uploaded.json()["document_version"]["id"])
    assert uploaded.json()["ingestion_job"]["status"] == "queued"

    # 2. Drive the parse worker to materialize chunks.
    from rag_eval_api.parsers.registry import ParserRegistry
    from rag_eval_api.services.worker import IngestionWorker

    ingestion_worker = IngestionWorker(
        session_factory=session_factory,
        blob_store=blob_store,  # type: ignore[arg-type]
        parser_registry=ParserRegistry(isolated=False),
        worker_id="e2e-ingestion-worker",
        lease_ttl=timedelta(seconds=30),
    )
    assert await ingestion_worker.run_once() is True

    detail = await client.get(f"/api/projects/{seed.project_id}/documents/{document_id}")
    assert detail.status_code == 200
    assert detail.json()["latest_version"]["parse_status"] == "succeeded"

    # 3. Create a candidate generation job and run the candidate worker.
    generation = await client.post(
        f"/api/projects/{seed.project_id}/documents/{document_id}/generate-candidates",
        headers={"Idempotency-Key": "e2e-gen-1"},
        json={
            "document_version_id": str(version_id),
            "dataset_name": "E2E 评测集",
            "capability_version": "candidate-generation-v1",
            "prompt_version": "prompt-v1",
            "seed": 5,
            "randomness": 0,
        },
    )
    assert generation.status_code == 202
    dataset_id = UUID(generation.json()["dataset_id"])
    dataset_version_id = UUID(generation.json()["dataset_version_id"])

    candidate_worker = CandidateWorker(
        session_factory=session_factory,
        generator=OpenAICompatibleFakeGenerator(),
        worker_id="e2e-candidate-worker",
        lease_ttl=timedelta(seconds=30),
    )
    gen_result = await candidate_worker.process_batch(1)
    assert gen_result.processed == 1
    assert gen_result.succeeded == 1

    # 4. Review (accept) the generated candidate item.
    items_page = await client.get(
        f"/api/projects/{seed.project_id}/candidate-datasets/{dataset_id}/versions/{dataset_version_id}/items"
    )
    assert items_page.status_code == 200
    items = items_page.json()["items"]
    assert len(items) == 1
    item_id = items[0]["id"]

    reviewed = await client.post(
        f"/api/projects/{seed.project_id}/candidate-datasets/{dataset_id}/versions/{dataset_version_id}/review",
        json={"item_id": item_id, "review_status": "accepted"},
    )
    assert reviewed.status_code == 200

    published = await client.post(
        f"/api/projects/{seed.project_id}/candidate-datasets/{dataset_id}/versions/{dataset_version_id}/publish"
    )
    assert published.status_code == 200

    # 5. Create model provider + adapter, then create and start the experiment.
    provider_resp = await client.post(
        f"/api/projects/{seed.project_id}/model-providers",
        headers={"Idempotency-Key": "e2e-provider-1"},
        json={
            "name": "E2E Provider",
            "endpoint": "https://provider.example.test/v1",
            "credential_ref": "TEST_TOKEN",
            "model_name": "e2e-model",
            "enabled": True,
        },
    )
    assert provider_resp.status_code == 201
    provider_id = provider_resp.json()["id"]

    adapter_resp = await client.post(
        f"/api/projects/{seed.project_id}/adapters",
        headers={"Idempotency-Key": "e2e-adapter-1"},
        json={
            "name": "E2E Adapter",
            "kind": "http",
            "endpoint": "https://adapter.example.test",
            "adapter_version": "adapter-v1",
            "trace_level": "minimal",
            "enabled": True,
        },
    )
    assert adapter_resp.status_code == 201
    adapter_id = adapter_resp.json()["id"]

    async with session_factory() as session:
        from sqlalchemy import update

        from rag_eval_api.models import AdapterConfig, AdapterTestStatus

        await session.execute(
            update(AdapterConfig)
            .where(AdapterConfig.id == UUID(adapter_id))
            .values(last_test_status=AdapterTestStatus.succeeded)
        )
        await session.commit()

    experiment_resp = await client.post(
        f"/api/projects/{seed.project_id}/experiments",
        headers={"Idempotency-Key": "e2e-exp-1"},
        json={
            "name": "E2E 实验",
            "dataset_version_id": str(dataset_version_id),
            "adapter_config_id": adapter_id,
            "model_provider_id": provider_id,
            "metric_versions": {
                "success_rate": "engineering-v1",
                "answer_nonempty_rate": "generation-v1",
                "average_latency_ms": "engineering-v1",
                "trace_coverage": "engineering-v1",
            },
            "parameters": {},
            "random_seed": 7,
        },
    )
    assert experiment_resp.status_code == 201
    experiment_id = experiment_resp.json()["id"]

    started = await client.post(
        f"/api/projects/{seed.project_id}/experiments/{experiment_id}/start"
    )
    assert started.status_code == 200
    run_id = started.json()["run"]["id"]

    # 6. Drive the experiment worker to completion.
    experiment_worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: ScriptedAdapter(),
        worker_id="e2e-experiment-worker",
        lease_ttl=timedelta(seconds=30),
        blob_store=blob_store,  # type: ignore[arg-type]
    )
    exp_result = await experiment_worker.process_batch(1)
    assert exp_result.processed == 1
    assert exp_result.succeeded == 1

    run_detail = await client.get(f"/api/projects/{seed.project_id}/experiments/runs/{run_id}")
    assert run_detail.status_code == 200
    assert run_detail.json()["status"] == "succeeded"

    # 7. Metrics calculated.
    metrics = await client.get(
        f"/api/projects/{seed.project_id}/experiments/{experiment_id}/metrics"
    )
    assert metrics.status_code == 200
    metric_by_key = {m["metric_key"]: m for m in metrics.json()}
    assert metric_by_key["success_rate"]["value"] == 1
    assert metric_by_key["answer_nonempty_rate"]["value"] == 1
    assert metric_by_key["trace_coverage"]["value"] == 1

    # 8. Trace persisted and sanitized.
    traces = await client.get(f"/api/projects/{seed.project_id}/traces", params={"run_id": run_id})
    assert traces.status_code == 200
    assert len(traces.json()) == 1
    trace_id = traces.json()[0]["trace_id"]
    trace_detail = await client.get(f"/api/projects/{seed.project_id}/traces/{trace_id}")
    assert trace_detail.status_code == 200

    # 9. No failure case for a successful run.
    failures = await client.get(
        f"/api/projects/{seed.project_id}/failures", params={"run_id": run_id}
    )
    assert failures.status_code == 200
    assert failures.json() == []

    regression = await client.get(f"/api/projects/{seed.project_id}/regression-cases")
    assert regression.status_code == 200
    assert regression.json() == []

    # 10. A failing run produces a failure case and can be promoted to a regression case.
    failing_experiment = await client.post(
        f"/api/projects/{seed.project_id}/experiments",
        headers={"Idempotency-Key": "e2e-exp-2"},
        json={
            "name": "E2E 失败实验",
            "dataset_version_id": str(dataset_version_id),
            "adapter_config_id": adapter_id,
            "model_provider_id": provider_id,
            "metric_versions": {"success_rate": "engineering-v1"},
            "parameters": {},
            "random_seed": 9,
        },
    )
    assert failing_experiment.status_code == 201
    failing_experiment_id = failing_experiment.json()["id"]
    failing_start = await client.post(
        f"/api/projects/{seed.project_id}/experiments/{failing_experiment_id}/start"
    )
    assert failing_start.status_code == 200
    failing_run_id = failing_start.json()["run"]["id"]

    failing_worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: ScriptedAdapter(fail=True),
        worker_id="e2e-experiment-worker-fail",
        lease_ttl=timedelta(seconds=30),
        blob_store=blob_store,  # type: ignore[arg-type]
    )
    failing_result = await failing_worker.process_batch(1)
    assert failing_result.processed == 1
    assert failing_result.failed == 1

    failing_failures = await client.get(
        f"/api/projects/{seed.project_id}/failures", params={"run_id": failing_run_id}
    )
    assert failing_failures.status_code == 200
    failure_rows = failing_failures.json()
    assert len(failure_rows) == 1
    assert failure_rows[0]["code"] == "adapter_error"
    assert failure_rows[0]["details"]["error_code"] == "upstream_error"

    promoted = await client.post(
        f"/api/projects/{seed.project_id}/regression-cases",
        headers={"Idempotency-Key": "e2e-regression-1"},
        json={
            "failure_case_id": failure_rows[0]["id"],
            "title": "E2E 回归样例",
            "notes": "Promoted from a deterministic failing run.",
        },
    )
    assert promoted.status_code == 201
    assert promoted.json()["status"] == "active"

    listed = await client.get(f"/api/projects/{seed.project_id}/regression-cases")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [promoted.json()["id"]]

    # 11. Aggregate usage rolls up onto the experiment row.
    failing_detail = await client.get(
        f"/api/projects/{seed.project_id}/experiments/{failing_experiment_id}"
    )
    assert failing_detail.status_code == 200
    assert failing_detail.json()["status"] == "failed"
    assert failing_detail.json()["failed_units"] >= 1
