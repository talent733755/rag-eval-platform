"""Tenant-scoped metric definitions and append-only result queries."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor, require_project_member
from rag_eval_api.db import get_db_session
from rag_eval_api.models import Experiment, ExperimentRun, MetricDefinition, MetricResult
from rag_eval_api.schemas.metrics import (
    MetricDefinitionResponse,
    MetricResultResponse,
    QualityGateCheckResponse,
    QualityGateRequest,
    QualityGateResponse,
)
from rag_eval_api.services.metric_calculation import calculate_run_metrics
from rag_eval_api.services.quality_gate import GateThreshold, evaluate_quality_gate

router = APIRouter(prefix="/api/projects/{project_id}", tags=["metrics"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": "not_found", "message": "Resource not found."}},
    )


async def _get_run(run_id: UUID, access: ProjectAccess, session: AsyncSession) -> ExperimentRun:
    run = await session.scalar(
        select(ExperimentRun).where(
            ExperimentRun.id == run_id,
            ExperimentRun.organization_id == access.actor.organization_id,
            ExperimentRun.project_id == access.project.id,
        )
    )
    if run is None:
        raise _not_found()
    return run


@router.get("/metric-definitions", response_model=list[MetricDefinitionResponse])
async def list_metric_definitions(
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[MetricDefinition]:
    return list(
        (
            await db_session.scalars(
                select(MetricDefinition)
                .where(
                    MetricDefinition.organization_id == access.actor.organization_id,
                    MetricDefinition.project_id == access.project.id,
                )
                .order_by(MetricDefinition.metric_key, MetricDefinition.version)
            )
        ).all()
    )


async def _list_results(
    *, run: ExperimentRun, session: AsyncSession, item_id: UUID | None = None
) -> list[MetricResult]:
    query = select(MetricResult).where(
        MetricResult.run_id == run.id,
        MetricResult.organization_id == run.organization_id,
        MetricResult.project_id == run.project_id,
    )
    if item_id is not None:
        query = query.where(MetricResult.run_item_id == item_id)
    return list(
        (await session.scalars(query.order_by(MetricResult.scope, MetricResult.metric_key))).all()
    )


@router.get("/experiments/{experiment_id}/metrics", response_model=list[MetricResultResponse])
async def list_experiment_metrics(
    experiment_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[MetricResult]:
    experiment = await db_session.scalar(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.organization_id == access.actor.organization_id,
            Experiment.project_id == access.project.id,
        )
    )
    if experiment is None:
        raise _not_found()
    return list(
        (
            await db_session.scalars(
                select(MetricResult)
                .where(
                    MetricResult.experiment_id == experiment.id,
                    MetricResult.organization_id == access.actor.organization_id,
                    MetricResult.project_id == access.project.id,
                )
                .order_by(MetricResult.created_at, MetricResult.scope, MetricResult.metric_key)
            )
        ).all()
    )


@router.get(
    "/experiments/{experiment_id}/runs/{run_id}/metrics", response_model=list[MetricResultResponse]
)
async def list_run_metrics(
    experiment_id: UUID,
    run_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[MetricResult]:
    run = await _get_run(run_id, access, db_session)
    if run.experiment_id != experiment_id:
        raise _not_found()
    return await _list_results(run=run, session=db_session)


@router.get(
    "/experiments/{experiment_id}/runs/{run_id}/items/{item_id}/metrics",
    response_model=list[MetricResultResponse],
)
async def list_sample_metrics(
    experiment_id: UUID,
    run_id: UUID,
    item_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[MetricResult]:
    run = await _get_run(run_id, access, db_session)
    if run.experiment_id != experiment_id:
        raise _not_found()
    results = await _list_results(run=run, session=db_session, item_id=item_id)
    if not results:
        raise _not_found()
    return results


@router.post(
    "/experiments/{experiment_id}/runs/{run_id}/metrics/recalculate",
    response_model=list[MetricResultResponse],
)
async def recalculate_run_metrics(
    experiment_id: UUID,
    run_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[MetricResult]:
    run = await _get_run(run_id, access, db_session)
    if run.experiment_id != experiment_id:
        raise _not_found()
    await calculate_run_metrics(db_session, run)
    await db_session.commit()
    return await _list_results(run=run, session=db_session)


@router.post(
    "/experiments/{experiment_id}/runs/{run_id}/quality-gate",
    response_model=QualityGateResponse,
)
async def evaluate_run_quality_gate(
    experiment_id: UUID,
    run_id: UUID,
    payload: QualityGateRequest,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> QualityGateResponse:
    """Deterministic pass/fail gate for CI; member-scoped and side-effect free.

    The verdict is derived from the run's aggregate (`scope=run`) metric values. A
    missing metric fails by default (`missing_is_pass=false`) and a run that has not
    completed cannot pass, so a pipeline never gates on partial or absent evidence.
    """

    run = await _get_run(run_id, access, db_session)
    if run.experiment_id != experiment_id:
        raise _not_found()
    results = await db_session.scalars(
        select(MetricResult).where(
            MetricResult.run_id == run.id,
            MetricResult.organization_id == access.actor.organization_id,
            MetricResult.project_id == access.project.id,
            MetricResult.scope == "run",
            MetricResult.scope_key == "run",
        )
    )
    metrics = {row.metric_key: row.value for row in results.all()}
    gate = evaluate_quality_gate(
        metrics,
        [
            GateThreshold(metric_key=t.metric_key, min_value=t.min_value, max_value=t.max_value)
            for t in payload.thresholds
        ],
        run_status=run.status.value,
        missing_is_pass=payload.missing_is_pass,
    )
    return QualityGateResponse(
        run_id=run.id,
        run_status=run.status.value,
        passed=gate.passed,
        incomplete=gate.incomplete,
        checks=[
            QualityGateCheckResponse(
                metric_key=c.metric_key,
                passed=c.passed,
                actual=c.actual,
                min_value=c.min_value,
                max_value=c.max_value,
                reason=c.reason,
            )
            for c in gate.checks
        ],
    )
