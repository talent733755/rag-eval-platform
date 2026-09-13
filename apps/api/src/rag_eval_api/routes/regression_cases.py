"""Project-scoped, idempotent regression case operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor, require_project_member
from rag_eval_api.db import get_db_session
from rag_eval_api.models import (
    CandidateDatasetItem,
    ExperimentRunItem,
    FailureCase,
    PersistedTrace,
    RegressionCase,
    RegressionCaseStatus,
)
from rag_eval_api.schemas.regression_cases import RegressionCaseCreate, RegressionCaseResponse
from rag_eval_api.services.audit import record_audit_event

router = APIRouter(prefix="/api/projects/{project_id}/regression-cases", tags=["regression-cases"])


def _error(code: str, message: str, status_code: int = 404) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": {"code": code, "message": message}}
    )


@router.get("", response_model=list[RegressionCaseResponse])
async def list_regression_cases(
    limit: int = Query(default=100, ge=1, le=100),
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[RegressionCase]:
    return list(
        (
            await db_session.scalars(
                select(RegressionCase)
                .where(
                    RegressionCase.organization_id == access.actor.organization_id,
                    RegressionCase.project_id == access.project.id,
                )
                .order_by(RegressionCase.created_at.desc())
                .limit(limit)
            )
        ).all()
    )


@router.post("", response_model=RegressionCaseResponse, status_code=status.HTTP_201_CREATED)
async def add_regression_case(
    payload: RegressionCaseCreate,
    idempotency_key: str = Header(min_length=1, max_length=255, alias="Idempotency-Key"),
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> RegressionCase:
    organization_id = access.actor.organization_id
    project_id = access.project.id
    existing = await db_session.scalar(
        select(RegressionCase).where(
            RegressionCase.organization_id == organization_id,
            RegressionCase.project_id == project_id,
            RegressionCase.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    failure = await db_session.scalar(
        select(FailureCase).where(
            FailureCase.id == payload.failure_case_id,
            FailureCase.organization_id == organization_id,
            FailureCase.project_id == project_id,
        )
    )
    if failure is None:
        raise _error("not_found", "Failure case was not found.")
    run_item = await db_session.scalar(
        select(ExperimentRunItem).where(
            ExperimentRunItem.id == failure.run_item_id,
            ExperimentRunItem.organization_id == organization_id,
            ExperimentRunItem.project_id == project_id,
        )
    )
    if run_item is None:
        raise _error(
            "candidate_provenance_unavailable", "Candidate provenance is unavailable.", 409
        )
    candidate = await db_session.scalar(
        select(CandidateDatasetItem).where(
            CandidateDatasetItem.id == run_item.candidate_item_id,
            CandidateDatasetItem.organization_id == organization_id,
            CandidateDatasetItem.project_id == project_id,
        )
    )
    if candidate is None or candidate.dataset_version_id is None:
        raise _error(
            "candidate_provenance_unavailable", "Candidate provenance is unavailable.", 409
        )
    trace_record = None
    if failure.trace_id is not None:
        trace_record = await db_session.scalar(
            select(PersistedTrace).where(
                PersistedTrace.run_item_id == failure.run_item_id,
                PersistedTrace.trace_id == failure.trace_id,
                PersistedTrace.organization_id == organization_id,
                PersistedTrace.project_id == project_id,
            )
        )
    regression_case = RegressionCase(
        organization_id=organization_id,
        project_id=project_id,
        failure_case_id=failure.id,
        run_item_id=failure.run_item_id,
        candidate_item_id=candidate.id,
        dataset_version_id=candidate.dataset_version_id,
        trace_record_id=trace_record.id if trace_record is not None else None,
        trace_id=failure.trace_id,
        idempotency_key=idempotency_key,
        title=payload.title,
        notes=payload.notes,
        status=RegressionCaseStatus.active,
        created_by=access.actor.user_id,
    )
    db_session.add(regression_case)
    record_audit_event(
        db_session,
        organization_id=organization_id,
        project_id=project_id,
        actor_id=access.actor.user_id,
        action="regression_case.added",
        resource_type="regression_case",
        resource_id=str(regression_case.id),
        metadata={"failure_case_id": str(failure.id), "run_item_id": str(failure.run_item_id)},
    )
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        replay = await db_session.scalar(
            select(RegressionCase).where(
                RegressionCase.organization_id == organization_id,
                RegressionCase.project_id == project_id,
                RegressionCase.idempotency_key == idempotency_key,
            )
        )
        if replay is not None:
            return replay
        raise _error(
            "regression_case_conflict", "Regression case conflicts with existing data.", 409
        ) from exc
    return regression_case
