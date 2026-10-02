"""Worker-judge integration: configured judge scores answer correctness."""

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
from rag_eval_api.judges.rule_based import RuleBasedJudge
from rag_eval_api.models import (
    AdapterConfig,
    AdapterKind,
    AdapterTestStatus,
    Base,
    CandidateDatasetItem,
    CandidateReviewStatus,
    Experiment,
    ExperimentRun,
    ExperimentRunItem,
    ExperimentRunStatus,
    ExperimentStatus,
    MetricResult,
)
from rag_eval_api.services.experiment_worker import ExperimentWorker


class _FixedAdapter:
    def run(self, request: Any) -> AdapterResponse:
        return AdapterResponse(
            request_id=request.request_id,
            answer="参考答案",
            usage={"latency_ms": 1},
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


async def _seed(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    org, proj, exp, adapter, candidate, run, item = (uuid4() for _ in range(7))
    async with session_factory() as session:
        session.add(
            Experiment(
                id=exp,
                organization_id=org,
                project_id=proj,
                name="判定实验",
                idempotency_key=f"judge-{uuid4()}",
                status=ExperimentStatus.queued,
                dataset_version_id=uuid4(),
                adapter_config_id=adapter,
                model_provider_id=uuid4(),
                metric_versions={"answer_correctness": "generation-v1"},
                parameters={},
                random_seed=1,
                configuration_snapshot={},
                environment_hash="e" * 64,
                total_units=1,
                created_by=uuid4(),
            )
        )
        session.add(
            AdapterConfig(
                id=adapter,
                organization_id=org,
                project_id=proj,
                name="判定 Adapter",
                kind=AdapterKind.http,
                endpoint="https://adapter.example.test",
                adapter_version="adapter-v1",
                trace_level="minimal",
                timeout_seconds=2,
                retry_count=0,
                enabled=True,
                last_test_status=AdapterTestStatus.succeeded,
            )
        )
        session.add(
            CandidateDatasetItem(
                id=candidate,
                organization_id=org,
                project_id=proj,
                dataset_id=uuid4(),
                dataset_version_id=None,
                generation_config_id=uuid4(),
                source_version_id=uuid4(),
                question="问题",
                question_type="factual",
                reference_answer="参考答案",
                confidence=1,
                automatic_checks={},
                review_status=CandidateReviewStatus.accepted,
                provenance={},
            )
        )
        session.add(
            ExperimentRun(
                id=run,
                organization_id=org,
                project_id=proj,
                experiment_id=exp,
                status=ExperimentRunStatus.queued,
                total_units=1,
                created_by=uuid4(),
            )
        )
        session.add(
            ExperimentRunItem(
                id=item,
                organization_id=org,
                project_id=proj,
                run_id=run,
                candidate_item_id=candidate,
            )
        )
        await session.commit()
    return {"run_id": run, "run_item_id": item}


@pytest.mark.asyncio
async def test_worker_persists_judge_verdict_and_metric(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: _FixedAdapter(),
        worker_id="judge-worker",
        lease_ttl=timedelta(seconds=30),
        judge_provider=RuleBasedJudge(),
    )
    result = await worker.process_batch(1)
    assert result.succeeded == 1

    async with session_factory() as session:
        item = await session.get(ExperimentRunItem, ids["run_item_id"])
        assert item is not None
        assert item.final_judge is not None
        assert item.final_judge["label"] == "correct"
        assert item.final_judge["confidence"] == 1.0
        metric = await session.scalar(
            select(MetricResult).where(
                MetricResult.run_id == ids["run_id"],
                MetricResult.metric_key == "answer_correctness",
                MetricResult.scope_key == "run",
            )
        )
        assert metric is not None
        assert metric.value == 1.0


@pytest.mark.asyncio
async def test_noop_judge_leaves_metric_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed(session_factory)
    worker = ExperimentWorker(
        session_factory=session_factory,
        adapter_factory=lambda config: _FixedAdapter(),
        worker_id="judge-worker-noop",
        lease_ttl=timedelta(seconds=30),
        # no judge_provider => default noop
    )
    result = await worker.process_batch(1)
    assert result.succeeded == 1

    async with session_factory() as session:
        item = await session.get(ExperimentRunItem, ids["run_item_id"])
        assert item is not None and item.final_judge is None
        metric = await session.scalar(
            select(MetricResult).where(
                MetricResult.run_id == ids["run_id"],
                MetricResult.metric_key == "answer_correctness",
                MetricResult.scope_key == "run",
            )
        )
        assert metric is not None
        assert metric.value is None
        assert metric.missing_reason == "judge_not_run"
