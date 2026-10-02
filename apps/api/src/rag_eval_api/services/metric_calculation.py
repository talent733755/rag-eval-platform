"""Versioned, deterministic calculation and persistence for completed runs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_eval_api.models import (
    Experiment,
    ExperimentRun,
    ExperimentRunItem,
    ExperimentRunItemStatus,
    ExperimentRunStatus,
    MetricDefinition,
    MetricResult,
    MetricScope,
)


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    name: str
    stage: str
    description: str
    kind: str
    unit: str


METRIC_SPECS: dict[str, MetricSpec] = {
    "retrieval": MetricSpec(
        "retrieval",
        "检索指标",
        "retrieval",
        "Retrieval metrics require persisted retrieval evidence.",
        "retrieval_unavailable",
        "ratio",
    ),
    "success_rate": MetricSpec(
        "success_rate",
        "成功率",
        "engineering",
        "Successful adapter responses / all run items.",
        "binary_success",
        "ratio",
    ),
    "failure_rate": MetricSpec(
        "failure_rate",
        "失败率",
        "engineering",
        "Failed adapter responses / all run items.",
        "binary_failure",
        "ratio",
    ),
    "completion_rate": MetricSpec(
        "completion_rate",
        "完成率",
        "engineering",
        "Terminal run items / all run items.",
        "completion",
        "ratio",
    ),
    "answer_nonempty_rate": MetricSpec(
        "answer_nonempty_rate",
        "非空答案率",
        "generation",
        "Successful items with a non-empty answer.",
        "answer_nonempty",
        "ratio",
    ),
    "answer_correctness": MetricSpec(
        "answer_correctness",
        "答案正确率",
        "generation",
        "Judge-scored answer correctness against the reference answer.",
        "judge_correctness",
        "ratio",
    ),
    "trace_coverage": MetricSpec(
        "trace_coverage",
        "Trace 覆盖率",
        "engineering",
        "Successful items carrying a trace identifier.",
        "trace_coverage",
        "ratio",
    ),
    "average_latency_ms": MetricSpec(
        "average_latency_ms",
        "平均延迟",
        "engineering",
        "Mean latency of successful items.",
        "latency",
        "milliseconds",
    ),
    "average_total_tokens": MetricSpec(
        "average_total_tokens",
        "平均 Token 数",
        "generation",
        "Mean reported total tokens of successful items.",
        "tokens",
        "tokens",
    ),
    "recall@5": MetricSpec(
        "recall@5",
        "Recall@5",
        "retrieval",
        "Retrieval recall at five against gold evidence.",
        "retrieval_recall",
        "ratio",
    ),
    "precision@5": MetricSpec(
        "precision@5",
        "Precision@5",
        "retrieval",
        "Retrieval precision at five against gold evidence.",
        "retrieval_precision",
        "ratio",
    ),
    "hit_rate@5": MetricSpec(
        "hit_rate@5",
        "HitRate@5",
        "retrieval",
        "Retrieval hit rate at five against gold evidence.",
        "retrieval_hit_rate",
        "ratio",
    ),
    "mrr": MetricSpec(
        "mrr",
        "MRR",
        "retrieval",
        "Mean reciprocal rank against gold evidence.",
        "retrieval_mrr",
        "ratio",
    ),
    "ndcg@5": MetricSpec(
        "ndcg@5",
        "nDCG@5",
        "retrieval",
        "Normalized discounted cumulative gain at five against gold evidence.",
        "retrieval_ndcg",
        "ratio",
    ),
}


@dataclass(frozen=True, slots=True)
class _Value:
    value: float | None
    numerator: float | None
    denominator: float | None
    missing_reason: str | None = None


def _definition_payload(spec: MetricSpec) -> dict[str, object]:
    return {"kind": spec.kind, "unit": spec.unit, "calculator": "metrics-v1"}


async def ensure_metric_definitions(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    metric_versions: dict[str, str],
    created_by: UUID,
) -> dict[tuple[str, str], MetricDefinition]:
    """Create missing definitions once; versions are never updated in place."""

    definitions: dict[tuple[str, str], MetricDefinition] = {}
    for key, version in metric_versions.items():
        existing = await session.scalar(
            select(MetricDefinition).where(
                MetricDefinition.organization_id == organization_id,
                MetricDefinition.project_id == project_id,
                MetricDefinition.metric_key == key,
                MetricDefinition.version == version,
            )
        )
        if existing is not None:
            definitions[(key, version)] = existing
            continue
        spec = METRIC_SPECS.get(
            key,
            MetricSpec(
                key,
                key,
                "custom",
                "Custom metric without a built-in calculator.",
                "unsupported",
                "unknown",
            ),
        )
        definition = MetricDefinition(
            organization_id=organization_id,
            project_id=project_id,
            metric_key=key,
            version=version,
            name=spec.name,
            description=spec.description,
            stage=spec.stage,
            definition=_definition_payload(spec),
            created_by=created_by,
        )
        session.add(definition)
        definitions[(key, version)] = definition
    await session.flush()
    return definitions


def _retrieval_value(spec: MetricSpec, relevant_ids: list[str], retrieved_ids: list[str]) -> _Value:
    """Compute a retrieval metric from gold evidence and persisted trace ids."""

    if not retrieved_ids:
        return _Value(None, None, None, "retrieval_evidence_unavailable")
    if not relevant_ids:
        return _Value(None, None, None, "no_relevant_evidence")
    from rag_eval_api.metrics.retrieval import (
        hit_rate_at_k,
        mean_reciprocal_rank,
        ndcg_at_k,
        precision_at_k,
        recall_at_k,
    )

    k = 5
    if spec.kind == "retrieval_mrr":
        value = mean_reciprocal_rank(retrieved_ids, relevant_ids)
    elif spec.kind == "retrieval_recall":
        value = recall_at_k(retrieved_ids, relevant_ids, k)
    elif spec.kind == "retrieval_precision":
        value = precision_at_k(retrieved_ids, relevant_ids, k)
    elif spec.kind == "retrieval_hit_rate":
        value = hit_rate_at_k(retrieved_ids, relevant_ids, k)
    else:
        value = ndcg_at_k(retrieved_ids, relevant_ids, k)
    if value is None:
        return _Value(None, None, None, "no_relevant_evidence")
    return _Value(float(value), float(value), 1.0)


def _sample_value(
    spec: MetricSpec,
    item: ExperimentRunItem,
    *,
    relevant_ids: list[str] | None = None,
    retrieved_ids: list[str] | None = None,
) -> _Value:
    status = item.status
    if spec.kind == "binary_success":
        return _Value(
            float(status is ExperimentRunItemStatus.succeeded),
            1.0 if status is ExperimentRunItemStatus.succeeded else 0.0,
            1.0,
        )
    if spec.kind == "binary_failure":
        return _Value(
            float(status is ExperimentRunItemStatus.failed),
            1.0 if status is ExperimentRunItemStatus.failed else 0.0,
            1.0,
        )
    if spec.kind == "completion":
        terminal = status in {
            ExperimentRunItemStatus.succeeded,
            ExperimentRunItemStatus.failed,
            ExperimentRunItemStatus.cancelled,
            ExperimentRunItemStatus.skipped,
        }
        return _Value(float(terminal), 1.0 if terminal else 0.0, 1.0)
    if status is not ExperimentRunItemStatus.succeeded:
        return _Value(None, None, None, "sample_not_successful")
    if spec.kind == "answer_nonempty":
        return _Value(
            float(bool(item.final_answer and item.final_answer.strip())),
            1.0 if item.final_answer and item.final_answer.strip() else 0.0,
            1.0,
        )
    if spec.kind == "judge_correctness":
        judge = item.final_judge
        if judge is None:
            return _Value(None, None, None, "judge_not_run")
        if judge.get("needs_review"):
            return _Value(None, None, None, "judge_low_confidence")
        label = judge.get("label")
        if label == "correct":
            return _Value(1.0, 1.0, 1.0)
        if label == "incorrect":
            return _Value(0.0, 0.0, 1.0)
        return _Value(None, None, None, "judge_unavailable")
    if spec.kind == "trace_coverage":
        return _Value(
            float(item.final_trace_id is not None), 1.0 if item.final_trace_id else 0.0, 1.0
        )
    if spec.kind == "latency":
        if item.final_latency_ms is None:
            return _Value(None, None, None, "latency_missing")
        return _Value(float(item.final_latency_ms), float(item.final_latency_ms), 1.0)
    if spec.kind == "tokens":
        total = (item.final_usage or {}).get("total_tokens")
        if not isinstance(total, int | float):
            return _Value(None, None, None, "token_usage_missing")
        return _Value(float(total), float(total), 1.0)
    if spec.kind == "retrieval_unavailable":
        return _Value(None, None, None, "retrieval_evidence_unavailable")
    if spec.kind in {
        "retrieval_recall",
        "retrieval_precision",
        "retrieval_hit_rate",
        "retrieval_mrr",
        "retrieval_ndcg",
    }:
        return _retrieval_value(spec, relevant_ids or [], retrieved_ids or [])
    return _Value(None, None, None, "metric_not_implemented")


def _distribution(values: list[float]) -> dict[str, object]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


async def _gold_evidence_by_item(
    session: AsyncSession, run: ExperimentRun, items: list[ExperimentRunItem]
) -> dict[UUID, list[str]]:
    """Load gold evidence chunk ids keyed by run item id (tenant-scoped)."""

    from rag_eval_api.models import CandidateItemEvidence

    candidate_ids = [item.candidate_item_id for item in items]
    if not candidate_ids:
        return {}
    rows = (
        await session.execute(
            select(CandidateItemEvidence.item_id, CandidateItemEvidence.chunk_id).where(
                CandidateItemEvidence.item_id.in_(candidate_ids),
                CandidateItemEvidence.organization_id == run.organization_id,
                CandidateItemEvidence.project_id == run.project_id,
            )
        )
    ).all()
    by_candidate: dict[UUID, list[str]] = {}
    for candidate_item_id, chunk_id in rows:
        by_candidate.setdefault(candidate_item_id, []).append(str(chunk_id))
    return {item.id: by_candidate.get(item.candidate_item_id, []) for item in items}


async def calculate_run_metrics(
    session: AsyncSession,
    run: ExperimentRun,
    *,
    retrieved_by_item: dict[UUID, list[str]] | None = None,
) -> int:
    """Append run and sample results; a repeated call is a no-op."""

    if run.status not in {
        ExperimentRunStatus.succeeded,
        ExperimentRunStatus.failed,
        ExperimentRunStatus.cancelled,
    }:
        return 0
    experiment = await session.scalar(
        select(Experiment).where(
            Experiment.id == run.experiment_id,
            Experiment.organization_id == run.organization_id,
            Experiment.project_id == run.project_id,
        )
    )
    if experiment is None:
        raise ValueError("metric calculation requires a tenant-scoped experiment")
    definitions = await ensure_metric_definitions(
        session,
        organization_id=run.organization_id,
        project_id=run.project_id,
        metric_versions=experiment.metric_versions,
        created_by=experiment.created_by,
    )
    items = list(
        (
            await session.scalars(
                select(ExperimentRunItem).where(
                    ExperimentRunItem.run_id == run.id,
                    ExperimentRunItem.organization_id == run.organization_id,
                    ExperimentRunItem.project_id == run.project_id,
                )
            )
        ).all()
    )
    existing = set(
        (
            await session.execute(
                select(MetricResult.scope_key, MetricResult.metric_definition_id).where(
                    MetricResult.run_id == run.id,
                    MetricResult.organization_id == run.organization_id,
                    MetricResult.project_id == run.project_id,
                )
            )
        ).all()
    )
    retrieved_by_item = retrieved_by_item or {}
    relevant_by_item = await _gold_evidence_by_item(session, run, items)
    created = 0
    for key, version in experiment.metric_versions.items():
        definition = definitions[(key, version)]
        spec = METRIC_SPECS.get(
            key,
            MetricSpec(
                key,
                key,
                "custom",
                "Custom metric without a built-in calculator.",
                "unsupported",
                "unknown",
            ),
        )
        sample_values = [
            _sample_value(
                spec,
                item,
                relevant_ids=relevant_by_item.get(item.id, []),
                retrieved_ids=retrieved_by_item.get(item.id, []),
            )
            for item in items
        ]
        available = [value.value for value in sample_values if value.value is not None]
        numerator_values = [
            value.numerator for value in sample_values if value.numerator is not None
        ]
        denominator_values = [
            value.denominator for value in sample_values if value.denominator is not None
        ]
        aggregate = _Value(
            sum(available) / len(available) if available else None,
            sum(numerator_values) if numerator_values else None,
            sum(denominator_values) if denominator_values else None,
            None
            if available
            else (sample_values[0].missing_reason if sample_values else "no_samples"),
        )
        provenance = {
            "calculator": "metrics-v1",
            "metric_key": key,
            "metric_version": version,
            "run_id": str(run.id),
        }
        aggregate_key = "run"
        if (aggregate_key, definition.id) not in existing:
            session.add(
                MetricResult(
                    organization_id=run.organization_id,
                    project_id=run.project_id,
                    experiment_id=run.experiment_id,
                    run_id=run.id,
                    metric_definition_id=definition.id,
                    metric_key=key,
                    metric_version=version,
                    scope=MetricScope.run,
                    scope_key=aggregate_key,
                    value=aggregate.value,
                    numerator=aggregate.numerator,
                    denominator=aggregate.denominator,
                    sample_count=len(items),
                    missing_reason=aggregate.missing_reason,
                    dimensions={},
                    distribution=_distribution([float(value) for value in available]),
                    provenance=provenance,
                )
            )
            created += 1
        for item, value in zip(items, sample_values, strict=True):
            sample_key = str(item.id)
            if (sample_key, definition.id) in existing:
                continue
            session.add(
                MetricResult(
                    organization_id=run.organization_id,
                    project_id=run.project_id,
                    experiment_id=run.experiment_id,
                    run_id=run.id,
                    run_item_id=item.id,
                    metric_definition_id=definition.id,
                    metric_key=key,
                    metric_version=version,
                    scope=MetricScope.sample,
                    scope_key=sample_key,
                    value=value.value,
                    numerator=value.numerator,
                    denominator=value.denominator,
                    sample_count=1,
                    missing_reason=value.missing_reason,
                    dimensions={"item_status": item.status.value},
                    distribution=_distribution([value.value] if value.value is not None else []),
                    provenance=provenance | {"run_item_id": sample_key},
                )
            )
            created += 1
    await session.flush()
    return created


async def calculate_completed_run_metrics(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> int:
    """Calculate metrics in a short transaction after a worker terminal transition."""

    from rag_eval_api.models import PersistedTrace
    from rag_eval_api.services.retrieval_evidence import extract_retrieved_chunk_ids

    async with session_factory() as session:
        async with session.begin():
            run = await session.scalar(select(ExperimentRun).where(ExperimentRun.id == run_id))
            if run is None:
                return 0
            traces = list(
                (
                    await session.scalars(
                        select(PersistedTrace).where(
                            PersistedTrace.run_id == run_id,
                            PersistedTrace.organization_id == run.organization_id,
                            PersistedTrace.project_id == run.project_id,
                        )
                    )
                ).all()
            )
            retrieved_by_item: dict[UUID, list[str]] = {
                trace.run_item_id: extract_retrieved_chunk_ids(trace.stages or [])
                for trace in traces
            }
            return await calculate_run_metrics(session, run, retrieved_by_item=retrieved_by_item)
