from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.adapters import AdapterResponse
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
