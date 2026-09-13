"""Project-scoped experiment draft and start endpoints."""

from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor, require_project_member
from rag_eval_api.db import get_db_session
from rag_eval_api.models import (
    AdapterConfig,
    CandidateDatasetItem,
    CandidateReviewStatus,
    Experiment,
    ExperimentRun,
    ExperimentRunItem,
    ExperimentRunItemStatus,
    ExperimentRunStatus,
    ExperimentStatus,
    ModelProviderConfig,
)
from rag_eval_api.schemas.experiments import (
    ExperimentDraftRequest,
    ExperimentResponse,
    ExperimentRunItemResponse,
    ExperimentRunResponse,
    ExperimentStartResponse,
)
from rag_eval_api.services.audit import record_audit_event
from rag_eval_api.services.experiment_snapshots import ExperimentSnapshotInput, create_snapshot
from rag_eval_api.services.experiment_validation import (
    ExperimentDraftValidationError,
    validate_experiment_draft,
)

router = APIRouter(prefix="/api/projects/{project_id}/experiments", tags=["experiments"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": {"code": code, "message": message}})


async def _get_experiment(
    experiment_id: UUID, access: ProjectAccess, db_session: AsyncSession
) -> Experiment:
    experiment = await db_session.scalar(
        select(Experiment).where(
            Experiment.id == experiment_id,
            Experiment.organization_id == access.actor.organization_id,
            Experiment.project_id == access.project.id,
        )
    )
    if experiment is None:
        raise _error(404, "not_found", "Resource not found.")
    return experiment


@router.get("", response_model=list[ExperimentResponse])
async def list_experiments(
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[Experiment]:
    return list(
        (
            await db_session.scalars(
                select(Experiment)
                .where(
                    Experiment.organization_id == access.actor.organization_id,
                    Experiment.project_id == access.project.id,
                )
                .order_by(Experiment.created_at.desc())
            )
        ).all()
    )


@router.post("", response_model=ExperimentResponse, status_code=status.HTTP_201_CREATED)
async def create_experiment(
    payload: ExperimentDraftRequest,
    idempotency_key: str = Header(min_length=1, max_length=255, alias="Idempotency-Key"),
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> Experiment:
    organization_id = access.actor.organization_id
    project_id = access.project.id
    try:
        validated = await validate_experiment_draft(db_session, access, payload)
    except ExperimentDraftValidationError as exc:
        status_code = 404 if exc.code == "not_found" else 409 if exc.code.endswith("unpublished") else 422
        raise _error(status_code, exc.code, str(exc)) from exc
    snapshot = create_snapshot(
        ExperimentSnapshotInput(
            dataset_version_id=validated.dataset_version_id,
            adapter_config_id=validated.adapter_config_id,
            adapter_version=validated.adapter_version,
            model_provider_id=validated.model_provider_id,
            model_name=validated.model_name,
            metric_versions=validated.metric_versions,
            parameters=validated.parameters,
            random_seed=validated.random_seed,
            environment={
                "platform": sys.platform,
                "python_version": platform.python_version(),
            },
        )
    )
    experiment = Experiment(
        organization_id=organization_id,
        project_id=project_id,
        name=validated.name,
        idempotency_key=idempotency_key,
        status=ExperimentStatus.draft,
        dataset_version_id=validated.dataset_version_id,
        adapter_config_id=validated.adapter_config_id,
        model_provider_id=validated.model_provider_id,
        metric_versions=validated.metric_versions,
        parameters=validated.parameters,
        random_seed=validated.random_seed,
        configuration_snapshot=snapshot.model_dump(mode="json"),
        environment_hash=snapshot.environment_hash,
        total_units=validated.dataset_item_count,
        created_by=access.actor.user_id,
    )
    db_session.add(experiment)
    record_audit_event(
        db_session,
        organization_id=organization_id,
        project_id=project_id,
        actor_id=access.actor.user_id,
        action="experiment.created",
        resource_type="experiment",
        resource_id=str(experiment.id),
        metadata={"status": "draft", "total_units": validated.dataset_item_count},
    )
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        existing = await db_session.scalar(
            select(Experiment).where(
                Experiment.organization_id == organization_id,
                Experiment.project_id == project_id,
                Experiment.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        raise _error(409, "experiment_idempotency_conflict", "Experiment request conflicts with an existing operation.") from exc
    return experiment


@router.post("/{experiment_id}/start", response_model=ExperimentStartResponse)
async def start_experiment(
    experiment_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Experiment | ExperimentRun]:
    experiment = await _get_experiment(experiment_id, access, db_session)
    if experiment.status is not ExperimentStatus.draft:
        raise _error(409, "experiment_already_started", "Only a draft experiment can be started.")
    adapter = await db_session.scalar(
        select(AdapterConfig).where(
            AdapterConfig.id == experiment.adapter_config_id,
            AdapterConfig.organization_id == access.actor.organization_id,
            AdapterConfig.project_id == access.project.id,
        )
    )
    provider = await db_session.scalar(
        select(ModelProviderConfig).where(
            ModelProviderConfig.id == experiment.model_provider_id,
            ModelProviderConfig.organization_id == access.actor.organization_id,
            ModelProviderConfig.project_id == access.project.id,
        )
    )
    if adapter is None or not adapter.enabled or adapter.last_test_status.value != "succeeded":
        raise _error(409, "adapter_unavailable", "Adapter is no longer available.")
    if provider is None or not provider.enabled:
        raise _error(409, "provider_unavailable", "Model provider is no longer available.")
    items = list(
        (
            await db_session.scalars(
                select(CandidateDatasetItem).where(
                    CandidateDatasetItem.dataset_version_id == experiment.dataset_version_id,
                    CandidateDatasetItem.organization_id == access.actor.organization_id,
                    CandidateDatasetItem.project_id == access.project.id,
                    CandidateDatasetItem.review_status == CandidateReviewStatus.accepted,
                )
            )
        ).all()
    )
    if not items:
        raise _error(409, "dataset_has_no_accepted_items", "Published dataset has no accepted items.")
    run = ExperimentRun(
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        experiment_id=experiment.id,
        status=ExperimentRunStatus.queued,
        total_units=len(items),
        created_by=access.actor.user_id,
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add_all(
        ExperimentRunItem(
            organization_id=access.actor.organization_id,
            project_id=access.project.id,
            run_id=run.id,
            candidate_item_id=item.id,
        )
        for item in items
    )
    experiment.status = ExperimentStatus.queued
    experiment.total_units = len(items)
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="experiment.started",
        resource_type="experiment",
        resource_id=str(experiment.id),
        metadata={"run_id": str(run.id), "total_units": len(items)},
    )
    await db_session.commit()
    return {"experiment": experiment, "run": run}


@router.get("/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(
    experiment_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> Experiment:
    return await _get_experiment(experiment_id, access, db_session)


async def _get_run(
    run_id: UUID, access: ProjectAccess, db_session: AsyncSession
) -> ExperimentRun:
    run = await db_session.scalar(
        select(ExperimentRun).where(
            ExperimentRun.id == run_id,
            ExperimentRun.organization_id == access.actor.organization_id,
            ExperimentRun.project_id == access.project.id,
        )
    )
    if run is None:
        raise _error(404, "not_found", "Resource not found.")
    return run


@router.get("/{experiment_id}/runs", response_model=list[ExperimentRunResponse])
async def list_experiment_runs(
    experiment_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[ExperimentRun]:
    await _get_experiment(experiment_id, access, db_session)
    return list(
        (
            await db_session.scalars(
                select(ExperimentRun)
                .where(
                    ExperimentRun.experiment_id == experiment_id,
                    ExperimentRun.organization_id == access.actor.organization_id,
                    ExperimentRun.project_id == access.project.id,
                )
                .order_by(ExperimentRun.created_at.desc())
            )
        ).all()
    )


@router.get("/runs/{run_id}", response_model=ExperimentRunResponse)
async def get_experiment_run(
    run_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> ExperimentRun:
    return await _get_run(run_id, access, db_session)


@router.get("/runs/{run_id}/items", response_model=list[ExperimentRunItemResponse])
async def list_experiment_run_items(
    run_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[ExperimentRunItem]:
    await _get_run(run_id, access, db_session)
    return list(
        (
            await db_session.scalars(
                select(ExperimentRunItem)
                .where(
                    ExperimentRunItem.run_id == run_id,
                    ExperimentRunItem.organization_id == access.actor.organization_id,
                    ExperimentRunItem.project_id == access.project.id,
                )
                .order_by(ExperimentRunItem.created_at, ExperimentRunItem.id)
            )
        ).all()
    )


@router.post("/runs/{run_id}/cancel", response_model=ExperimentRunResponse)
async def cancel_experiment_run(
    run_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> ExperimentRun:
    run = await _get_run(run_id, access, db_session)
    if run.status in {ExperimentRunStatus.succeeded, ExperimentRunStatus.failed, ExperimentRunStatus.cancelled}:
        raise _error(409, "run_not_cancellable", "Run is already terminal.")
    now = datetime.now(UTC)
    if run.status is ExperimentRunStatus.queued:
        queued_items = list(
            (
                await db_session.scalars(
                    select(ExperimentRunItem)
                    .where(
                        ExperimentRunItem.run_id == run.id,
                        ExperimentRunItem.status == ExperimentRunItemStatus.queued,
                    )
                    .with_for_update()
                )
            ).all()
        )
        for item in queued_items:
            item.status = ExperimentRunItemStatus.cancelled
            item.completed_at = now
            run.skipped_units += 1
            run.completed_units += 1
        run.status = ExperimentRunStatus.cancelled
        run.completed_at = now
    else:
        run.status = ExperimentRunStatus.cancelling
    experiment = await db_session.get(Experiment, run.experiment_id)
    if experiment is not None:
        experiment.status = ExperimentStatus.cancelled if run.status is ExperimentRunStatus.cancelled else ExperimentStatus.cancelling
        if run.status is ExperimentRunStatus.cancelled:
            experiment.completed_at = now
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="experiment.run_cancel_requested",
        resource_type="experiment_run",
        resource_id=str(run.id),
        metadata={"status": run.status.value},
    )
    await db_session.commit()
    return run


@router.post("/runs/{run_id}/items/{item_id}/retry", response_model=ExperimentRunItemResponse)
async def retry_experiment_run_item(
    run_id: UUID,
    item_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> ExperimentRunItem:
    run = await _get_run(run_id, access, db_session)
    item = await db_session.scalar(
        select(ExperimentRunItem).where(
            ExperimentRunItem.id == item_id,
            ExperimentRunItem.run_id == run.id,
            ExperimentRunItem.organization_id == access.actor.organization_id,
            ExperimentRunItem.project_id == access.project.id,
        )
    )
    if item is None:
        raise _error(404, "not_found", "Resource not found.")
    if item.status is not ExperimentRunItemStatus.failed:
        raise _error(409, "item_not_retryable", "Only failed run items can be retried.")
    item.status = ExperimentRunItemStatus.queued
    item.error_code = None
    item.error_message = None
    item.completed_at = None
    run.status = ExperimentRunStatus.queued
    run.completed_at = None
    run.completed_units = max(0, run.completed_units - 1)
    run.failed_units = max(0, run.failed_units - 1)
    run.worker_id = None
    run.lease_expires_at = None
    run.heartbeat_at = None
    experiment = await db_session.get(Experiment, run.experiment_id)
    if experiment is not None:
        experiment.status = ExperimentStatus.queued
        experiment.completed_at = None
        experiment.completed_units = max(0, experiment.completed_units - 1)
        experiment.failed_units = max(0, experiment.failed_units - 1)
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="experiment.run_item_retried",
        resource_type="experiment_run_item",
        resource_id=str(item.id),
        metadata={"run_id": str(run.id)},
    )
    await db_session.commit()
    return item
