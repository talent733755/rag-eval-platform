from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.adapters import AdapterResponse
from rag_eval_api.adapters.errors import AdapterError
from rag_eval_api.models import (
    AdapterConfig,
    AdapterKind,
    AdapterTestStatus,
    Base,
    CandidateDatasetItem,
    CandidateReviewStatus,
    Experiment,
    ExperimentRun,
    ExperimentRunAttempt,
    ExperimentRunItem,
    ExperimentRunItemStatus,
    ExperimentRunStatus,
    ExperimentStatus,
    MetricResult,
    PersistedTrace,
)
from rag_eval_api.services.experiment_worker import ExperimentWorker
from rag_eval_api.services.metric_calculation import calculate_completed_run_metrics


class FakeAdapter:
    def run(self, request: Any) -> AdapterResponse:
        return AdapterResponse(
            request_id=request.request_id,
            answer="测试答案",
            usage={"latency_ms": 3},
            trace={
                "trace_id": "trace-worker-1",
                "level": "minimal",
                "stages": {"retrieve": {"ids": ["chunk-1"], "authorization": "do-not-store"}},
            },
        )


class ScriptedAdapter:
    """Replay a scripted sequence of outcomes and count invocations."""

    def __init__(self, outcomes: list[Exception | None], usage: dict[str, Any] | None = None):
        self.outcomes = outcomes
        self.usage = usage or {"latency_ms": 5}
        self.calls = 0

    def run(self, request: Any) -> AdapterResponse:
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return AdapterResponse(
            request_id=request.request_id,
            answer="脚本答案",
            usage=self.usage,
        )


async def _seed_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    item_count: int,
    retry_count: int = 0,
    run_status: ExperimentRunStatus = ExperimentRunStatus.queued,
) -> dict[str, Any]:
    organization_id, project_id = uuid4(), uuid4()
    experiment_id, adapter_id = uuid4(), uuid4()
    run_id = uuid4()
    experiment = Experiment(
        id=experiment_id,
        organization_id=organization_id,
        project_id=project_id,
        name="脚本实验",
        idempotency_key=f"scripted-{uuid4()}",
        status=ExperimentStatus.queued,
        dataset_version_id=uuid4(),
        adapter_config_id=adapter_id,
        model_provider_id=uuid4(),
        metric_versions={
            "success_rate": "engineering-v1",
            "answer_nonempty_rate": "generation-v1",
            "average_latency_ms": "engineering-v1",
        },
        parameters={},
        random_seed=1,
        configuration_snapshot={},
        environment_hash="b" * 64,
        total_units=item_count,
        created_by=uuid4(),
    )
    adapter = AdapterConfig(
        id=adapter_id,
        organization_id=organization_id,
        project_id=project_id,
        name="脚本 Adapter",
        kind=AdapterKind.http,
        endpoint="https://adapter.example.test",
        adapter_version="adapter-v1",
        trace_level="minimal",
        timeout_seconds=5,
        retry_count=retry_count,
        enabled=True,
        last_test_status=AdapterTestStatus.succeeded,
    )
    run = ExperimentRun(
        id=run_id,
        organization_id=organization_id,
        project_id=project_id,
        experiment_id=experiment_id,
        status=run_status,
        total_units=item_count,
        created_by=uuid4(),
    )
    items: list[ExperimentRunItem] = []
    candidates: list[CandidateDatasetItem] = []
    for index in range(item_count):
        candidate_id = uuid4()
        candidates.append(
            CandidateDatasetItem(
                id=candidate_id,
                organization_id=organization_id,
                project_id=project_id,
                dataset_id=uuid4(),
                dataset_version_id=None,
                generation_config_id=uuid4(),
                source_version_id=uuid4(),
                question=f"问题 {index}",
                question_type="factual",
                reference_answer="参考答案",
                confidence=1,
                automatic_checks={},
                review_status=CandidateReviewStatus.accepted,
                provenance={},
            )
        )
        items.append(
            ExperimentRunItem(
                id=uuid4(),
                organization_id=organization_id,
                project_id=project_id,
                run_id=run_id,
                candidate_item_id=candidate_id,
            )
        )
    async with session_factory() as session:
        session.add(experiment)
        session.add(adapter)
        session.add(run)
        session.add_all(candidates)
        session.add_all(items)
        await session.commit()
    return {
        "organization_id": organization_id,
        "project_id": project_id,
        "experiment_id": experiment_id,
        "adapter_id": adapter_id,
        "run_id": run_id,
        "item_ids": [item.id for item in items],
    }


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_experiment_worker_records_success_and_attempt_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    organization_id, project_id = uuid4(), uuid4()
    experiment_id, adapter_id, candidate_id, run_id, run_item_id = (uuid4() for _ in range(5))
    experiment = Experiment(
        id=experiment_id,
        organization_id=organization_id,
        project_id=project_id,
        name="Worker 实验",
        idempotency_key="worker-test",
        status=ExperimentStatus.queued,
        dataset_version_id=uuid4(),
        adapter_config_id=adapter_id,
        model_provider_id=uuid4(),
        metric_versions={
            "retrieval": "v1",
            "success_rate": "engineering-v1",
            "answer_nonempty_rate": "generation-v1",
            "average_latency_ms": "engineering-v1",
            "trace_coverage": "engineering-v1",
        },
        parameters={},
        random_seed=1,
        configuration_snapshot={},
        environment_hash="a" * 64,
        total_units=1,
        created_by=uuid4(),
    )
    adapter = AdapterConfig(
        id=adapter_id,
        organization_id=organization_id,
        project_id=project_id,
        name="Worker Adapter",
        kind=AdapterKind.http,
        endpoint="https://adapter.example.test",
        adapter_version="adapter-v1",
        trace_level="minimal",
        timeout_seconds=2,
        retry_count=0,
        enabled=True,
        last_test_status=AdapterTestStatus.succeeded,
    )
    candidate = CandidateDatasetItem(
        id=candidate_id,
        organization_id=organization_id,
        project_id=project_id,
        dataset_id=uuid4(),
        dataset_version_id=None,
        generation_config_id=uuid4(),
        source_version_id=uuid4(),
        question="测试问题",
        question_type="factual",
        reference_answer="参考答案",
        confidence=1,
        automatic_checks={},
        review_status=CandidateReviewStatus.accepted,
        provenance={},
    )
    run = ExperimentRun(
        id=run_id,
        organization_id=organization_id,
        project_id=project_id,
        experiment_id=experiment_id,
        status=ExperimentRunStatus.queued,
        total_units=1,
        created_by=uuid4(),
    )
    run_item = ExperimentRunItem(
        id=run_item_id,
        organization_id=organization_id,
        project_id=project_id,
        run_id=run_id,
        candidate_item_id=candidate_id,
    )
    async with session_factory() as session:
        session.add_all([experiment, adapter, candidate, run, run_item])
        await session.commit()

    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: FakeAdapter(),
        worker_id="experiment-worker-test",
        lease_ttl=timedelta(seconds=30),
    )
    result = await worker.process_batch(1)

    assert result.processed == 1
    assert result.succeeded == 1
    async with session_factory() as session:
        stored_item = await session.get(ExperimentRunItem, run_item_id)
        stored_run = await session.get(ExperimentRun, run_id)
        attempt = await session.scalar(
            select(ExperimentRunAttempt).where(ExperimentRunAttempt.run_item_id == run_item_id)
        )
        metric_results = list(
            (
                await session.scalars(
                    select(MetricResult).where(
                        MetricResult.run_id == run_id,
                        MetricResult.scope_key == "run",
                    )
                )
            ).all()
        )
        trace = await session.scalar(
            select(PersistedTrace).where(PersistedTrace.run_item_id == run_item_id)
        )
        assert stored_item is not None and stored_item.status is ExperimentRunItemStatus.succeeded
        assert stored_item.final_answer == "测试答案"
        assert stored_run is not None and stored_run.status is ExperimentRunStatus.succeeded
        assert attempt is not None and attempt.attempt_number == 1
        by_key = {result.metric_key: result for result in metric_results}
        assert by_key["retrieval"].missing_reason == "retrieval_evidence_unavailable"
        assert by_key["success_rate"].value == 1
        assert by_key["answer_nonempty_rate"].value == 1
        assert by_key["average_latency_ms"].value == 3
        assert by_key["trace_coverage"].value == 1
        assert trace is not None
        assert trace.trace_id == "trace-worker-1"
        assert "authorization" not in str(trace.stages)

    assert await calculate_completed_run_metrics(session_factory, run_id) == 0


@pytest.mark.asyncio
async def test_experiment_worker_retries_retryable_failure_until_success(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_run(session_factory, item_count=1, retry_count=2)
    adapter = ScriptedAdapter(
        [AdapterError("adapter_unavailable", "暂时不可用", retryable=True), None]
    )
    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: adapter,
        worker_id="experiment-worker-retry",
        lease_ttl=timedelta(seconds=30),
    )

    result = await worker.process_batch(5)

    assert result.succeeded == 1
    assert adapter.calls == 2
    async with session_factory() as session:
        item = await session.get(ExperimentRunItem, ids["item_ids"][0])
        run = await session.get(ExperimentRun, ids["run_id"])
        attempts = list(
            (
                await session.scalars(
                    select(ExperimentRunAttempt)
                    .where(ExperimentRunAttempt.run_item_id == ids["item_ids"][0])
                    .order_by(ExperimentRunAttempt.attempt_number)
                )
            ).all()
        )
        assert item is not None and item.status is ExperimentRunItemStatus.succeeded
        assert item.attempt_count == 2
        assert run is not None and run.status is ExperimentRunStatus.succeeded
        assert run.failed_units == 0
        assert [attempt.status for attempt in attempts] == [
            ExperimentRunItemStatus.failed,
            ExperimentRunItemStatus.succeeded,
        ]
        assert attempts[0].error_code == "adapter_unavailable"


@pytest.mark.asyncio
async def test_experiment_worker_marks_item_failed_after_retry_exhausted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_run(session_factory, item_count=1, retry_count=1)
    adapter = ScriptedAdapter([AdapterError("adapter_unavailable", "持续不可用", retryable=True)])
    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: adapter,
        worker_id="experiment-worker-exhaust",
        lease_ttl=timedelta(seconds=30),
    )

    result = await worker.process_batch(5)

    assert result.failed == 1
    # retry_count=1 允许 1 次初始尝试 + 1 次重试。
    assert adapter.calls == 2
    async with session_factory() as session:
        item = await session.get(ExperimentRunItem, ids["item_ids"][0])
        run = await session.get(ExperimentRun, ids["run_id"])
        attempts = list(
            (
                await session.scalars(
                    select(ExperimentRunAttempt).where(
                        ExperimentRunAttempt.run_item_id == ids["item_ids"][0]
                    )
                )
            ).all()
        )
        assert item is not None and item.status is ExperimentRunItemStatus.failed
        assert item.attempt_count == 2
        assert item.error_code == "adapter_unavailable"
        assert run is not None and run.status is ExperimentRunStatus.failed
        assert run.failed_units == 1
        assert len(attempts) == 2


@pytest.mark.asyncio
async def test_experiment_worker_does_not_retry_non_retryable_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_run(session_factory, item_count=1, retry_count=5)
    adapter = ScriptedAdapter(
        [AdapterError("adapter_invalid_response", "响应不合法", retryable=False)]
    )
    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: adapter,
        worker_id="experiment-worker-nonretryable",
        lease_ttl=timedelta(seconds=30),
    )

    result = await worker.process_batch(5)

    assert result.failed == 1
    assert adapter.calls == 1
    async with session_factory() as session:
        item = await session.get(ExperimentRunItem, ids["item_ids"][0])
        assert item is not None and item.status is ExperimentRunItemStatus.failed
        assert item.attempt_count == 1


@pytest.mark.asyncio
async def test_experiment_worker_cancels_queued_items_when_run_cancelling(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_run(session_factory, item_count=3, run_status=ExperimentRunStatus.cancelling)
    adapter = ScriptedAdapter([None])
    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: adapter,
        worker_id="experiment-worker-cancel",
        lease_ttl=timedelta(seconds=30),
    )

    await worker.process_batch(5)

    assert adapter.calls == 0
    async with session_factory() as session:
        run = await session.get(ExperimentRun, ids["run_id"])
        experiment = await session.get(Experiment, ids["experiment_id"])
        items = list(
            (
                await session.scalars(
                    select(ExperimentRunItem).where(ExperimentRunItem.run_id == ids["run_id"])
                )
            ).all()
        )
        assert run is not None and run.status is ExperimentRunStatus.cancelled
        assert run.completed_at is not None
        assert run.skipped_units == 3
        assert experiment is not None and experiment.status is ExperimentStatus.cancelled
        assert all(item.status is ExperimentRunItemStatus.cancelled for item in items)


@pytest.mark.asyncio
async def test_experiment_worker_aggregates_usage_totals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_run(session_factory, item_count=2)
    adapter = ScriptedAdapter(
        [None, None],
        usage={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14, "latency_ms": 5},
    )
    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: adapter,
        worker_id="experiment-worker-usage",
        lease_ttl=timedelta(seconds=30),
    )

    result = await worker.process_batch(5)

    assert result.succeeded == 2
    async with session_factory() as session:
        run = await session.get(ExperimentRun, ids["run_id"])
        experiment = await session.get(Experiment, ids["experiment_id"])
        assert run is not None and run.status is ExperimentRunStatus.succeeded
        assert run.total_input_tokens == 20
        assert run.total_output_tokens == 8
        assert run.total_tokens == 28
        assert run.total_latency_ms == 10
        assert experiment is not None
        assert experiment.total_input_tokens == 20
        assert experiment.total_tokens == 28
        assert experiment.total_latency_ms == 10


@pytest.mark.asyncio
async def test_experiment_worker_maintenance_finalizes_cancelling_run_with_expired_lease(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_run(session_factory, item_count=1)
    async with session_factory() as session:
        run = await session.get(ExperimentRun, ids["run_id"])
        item = await session.get(ExperimentRunItem, ids["item_ids"][0])
        assert run is not None and item is not None
        expired = datetime.now(UTC) - timedelta(seconds=5)
        run.status = ExperimentRunStatus.cancelling
        run.worker_id = "crashed-worker"
        run.lease_expires_at = expired
        run.heartbeat_at = expired
        item.status = ExperimentRunItemStatus.processing
        item.started_at = expired
        await session.commit()
    adapter = ScriptedAdapter([None])
    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: adapter,
        worker_id="experiment-worker-maintenance",
        lease_ttl=timedelta(seconds=30),
    )

    await worker.run_maintenance()

    assert adapter.calls == 0
    async with session_factory() as session:
        run = await session.get(ExperimentRun, ids["run_id"])
        item = await session.get(ExperimentRunItem, ids["item_ids"][0])
        experiment = await session.get(Experiment, ids["experiment_id"])
        assert run is not None and run.status is ExperimentRunStatus.cancelled
        assert item is not None and item.status is ExperimentRunItemStatus.cancelled
        assert experiment is not None and experiment.status is ExperimentStatus.cancelled
