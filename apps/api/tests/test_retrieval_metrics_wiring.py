"""Retrieval metrics computed from persisted traces vs gold evidence (adapter-v2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rag_eval_api.models import (
    Base,
    CandidateDatasetItem,
    CandidateItemEvidence,
    CandidateReviewStatus,
    Experiment,
    ExperimentRun,
    ExperimentRunItem,
    ExperimentRunItemStatus,
    ExperimentRunStatus,
    ExperimentStatus,
    MetricResult,
    MetricScope,
)
from rag_eval_api.services.failure_diagnosis import classify_failure
from rag_eval_api.services.metric_calculation import calculate_run_metrics
from rag_eval_api.services.retrieval_evidence import (
    extract_retrieved_chunk_ids,
    resolve_relevant_chunk_ids,
)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _ids(count: int) -> list:
    return [uuid4() for _ in range(count)]


async def _seed_run_with_retrieval(
    session: AsyncSession,
    *,
    gold_chunk_ids: list,
    metric_versions: dict[str, str],
    trace_retrieved_ids: list[str],
) -> dict:
    org, proj, exp, run, candidate, item = _ids(6)
    source_version = uuid4()
    experiment = Experiment(
        id=exp,
        organization_id=org,
        project_id=proj,
        name="检索实验",
        idempotency_key=f"retrieval-{uuid4()}",
        status=ExperimentStatus.succeeded,
        dataset_version_id=uuid4(),
        adapter_config_id=uuid4(),
        model_provider_id=uuid4(),
        metric_versions=metric_versions,
        parameters={},
        random_seed=1,
        configuration_snapshot={},
        environment_hash="c" * 64,
        total_units=1,
        created_by=uuid4(),
    )
    run_obj = ExperimentRun(
        id=run,
        organization_id=org,
        project_id=proj,
        experiment_id=exp,
        status=ExperimentRunStatus.succeeded,
        total_units=1,
        created_by=uuid4(),
    )
    candidate_obj = CandidateDatasetItem(
        id=candidate,
        organization_id=org,
        project_id=proj,
        dataset_id=uuid4(),
        dataset_version_id=None,
        generation_config_id=uuid4(),
        source_version_id=source_version,
        question="问题",
        question_type="factual",
        reference_answer="参考答案",
        confidence=1,
        automatic_checks={},
        review_status=CandidateReviewStatus.accepted,
        provenance={},
    )
    evidence = [
        CandidateItemEvidence(
            organization_id=org,
            project_id=proj,
            item_id=candidate,
            source_version_id=source_version,
            chunk_id=chunk_id,
            ordinal=index,
        )
        for index, chunk_id in enumerate(gold_chunk_ids)
    ]
    run_item = ExperimentRunItem(
        id=item,
        organization_id=org,
        project_id=proj,
        run_id=run,
        candidate_item_id=candidate,
        status=ExperimentRunItemStatus.succeeded,
        final_answer="答案",
        final_trace_id="trace-retrieval-1",
    )
    session.add_all([experiment, run_obj, candidate_obj, *evidence, run_item])
    await session.commit()
    return {
        "run": run_obj,
        "run_item_id": item,
        "trace_retrieved_ids": trace_retrieved_ids,
        "gold_chunk_ids": gold_chunk_ids,
    }


@pytest.mark.asyncio
async def test_recall_computed_from_trace_and_gold_evidence(session: AsyncSession) -> None:
    gold_a, gold_b = uuid4(), uuid4()
    retrieved = [str(gold_a), "noise-1", "noise-2", "noise-3", "noise-4"]
    data = await _seed_run_with_retrieval(
        session,
        gold_chunk_ids=[gold_a, gold_b],
        metric_versions={"recall@5": "retrieval-v1", "hit_rate@5": "retrieval-v1"},
        trace_retrieved_ids=retrieved,
    )
    run = data["run"]

    # Feed the persisted retrieval ids into calculation (adapter-v2 contract).
    retrieved_ids = extract_retrieved_chunk_ids(
        [{"name": "retrieve", "payload": {"ids": data["trace_retrieved_ids"]}}]
    )
    assert retrieved_ids == retrieved

    created = await calculate_run_metrics(
        session, run, retrieved_by_item={data["run_item_id"]: retrieved_ids}
    )
    assert created > 0

    rows = (
        (
            await session.execute(
                __import__("sqlalchemy")
                .select(MetricResult)
                .where(MetricResult.run_id == run.id, MetricResult.scope == MetricScope.run)
            )
        )
        .scalars()
        .all()
    )
    by_key = {row.metric_key: row for row in rows}
    # recall@5 = 1 of 2 gold chunks retrieved => 0.5
    assert by_key["recall@5"].value == pytest.approx(0.5)
    assert by_key["recall@5"].missing_reason is None
    # hit_rate@5 = at least one gold chunk hit => 1.0
    assert by_key["hit_rate@5"].value == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_no_gold_evidence_marks_metric_missing_not_zero(session: AsyncSession) -> None:
    data = await _seed_run_with_retrieval(
        session,
        gold_chunk_ids=[],
        metric_versions={"recall@5": "retrieval-v1"},
        trace_retrieved_ids=["chunk-1"],
    )
    run = data["run"]
    retrieved_ids = ["chunk-1"]
    await calculate_run_metrics(
        session, run, retrieved_by_item={data["run_item_id"]: retrieved_ids}
    )
    rows = (
        (
            await session.execute(
                __import__("sqlalchemy")
                .select(MetricResult)
                .where(
                    MetricResult.run_id == run.id,
                    MetricResult.scope == MetricScope.run,
                    MetricResult.metric_key == "recall@5",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows[0].value is None
    assert rows[0].missing_reason == "no_relevant_evidence"


@pytest.mark.asyncio
async def test_missing_retrieval_trace_marks_unavailable(session: AsyncSession) -> None:
    gold = uuid4()
    data = await _seed_run_with_retrieval(
        session,
        gold_chunk_ids=[gold],
        metric_versions={"recall@5": "retrieval-v1"},
        trace_retrieved_ids=[],
    )
    run = data["run"]
    # No structured retrieval stage at all.
    await calculate_run_metrics(session, run, retrieved_by_item={})
    rows = (
        (
            await session.execute(
                __import__("sqlalchemy")
                .select(MetricResult)
                .where(
                    MetricResult.run_id == run.id,
                    MetricResult.scope == MetricScope.run,
                    MetricResult.metric_key == "recall@5",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows[0].value is None
    assert rows[0].missing_reason == "retrieval_evidence_unavailable"


def test_retrieval_miss_diagnosis_fires_when_gold_not_retrieved() -> None:
    retrieved = ["noise-1", "noise-2"]
    gold = resolve_relevant_chunk_ids(["gold-1"])
    relevant_retrieved = bool(set(retrieved) & set(gold))

    diagnosis = classify_failure(relevant_retrieved=relevant_retrieved)

    assert diagnosis is not None
    assert diagnosis.code == "retrieval_miss"
    assert diagnosis.retryable is False


def test_retrieval_hit_does_not_flag_retrieval_miss() -> None:
    retrieved = ["gold-1", "noise-2"]
    gold = resolve_relevant_chunk_ids(["gold-1"])
    relevant_retrieved = bool(set(retrieved) & set(gold))

    diagnosis = classify_failure(relevant_retrieved=relevant_retrieved)

    assert diagnosis is None
