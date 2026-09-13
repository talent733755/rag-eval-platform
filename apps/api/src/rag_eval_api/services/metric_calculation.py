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
        "Retrieval recall at five; requires persisted retrieval evidence.",
        "retrieval_unavailable",
        "ratio",
    ),
    "precision@5": MetricSpec(
        "precision@5",
        "Precision@5",
        "retrieval",
        "Retrieval precision at five; requires persisted retrieval evidence.",
        "retrieval_unavailable",
        "ratio",
    ),
    "hit_rate@5": MetricSpec(
        "hit_rate@5",
        "HitRate@5",
        "retrieval",
        "Retrieval hit rate at five; requires persisted retrieval evidence.",
        "retrieval_unavailable",
        "ratio",
    ),
    "mrr": MetricSpec(
        "mrr",
        "MRR",
        "retrieval",
        "Mean reciprocal rank; requires persisted retrieval evidence.",
        "retrieval_unavailable",
        "ratio",
    ),
    "ndcg@5": MetricSpec(
        "ndcg@5",
        "nDCG@5",
        "retrieval",
        "Normalized discounted cumulative gain at five; requires persisted retrieval evidence.",
        "retrieval_unavailable",
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


def _sample_value(spec: MetricSpec, item: ExperimentRunItem) -> _Value:
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


async def calculate_run_metrics(session: AsyncSession, run: ExperimentRun) -> int:
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
        sample_values = [_sample_value(spec, item) for item in items]
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

    async with session_factory() as session:
        async with session.begin():
            run = await session.scalar(select(ExperimentRun).where(ExperimentRun.id == run_id))
            if run is None:
                return 0
            return await calculate_run_metrics(session, run)
