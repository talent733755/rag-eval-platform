"""Tenant-scoped Trace and failure diagnosis queries."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess, require_project_member
from rag_eval_api.db import get_db_session
from rag_eval_api.models import FailureCase, PersistedTrace
from rag_eval_api.schemas.traces import FailureCaseResponse, TraceResponse

router = APIRouter(prefix="/api/projects/{project_id}", tags=["diagnostics"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": "not_found", "message": "Resource not found."}},
    )


@router.get("/traces", response_model=list[TraceResponse])
async def list_traces(
    run_id: UUID | None = None,
    run_item_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[PersistedTrace]:
    query = select(PersistedTrace).where(
        PersistedTrace.organization_id == access.actor.organization_id,
        PersistedTrace.project_id == access.project.id,
    )
    if run_id is not None:
        query = query.where(PersistedTrace.run_id == run_id)
    if run_item_id is not None:
        query = query.where(PersistedTrace.run_item_id == run_item_id)
    return list(
        (
            await db_session.scalars(query.order_by(PersistedTrace.created_at.desc()).limit(limit))
        ).all()
    )


@router.get("/traces/{trace_id}", response_model=TraceResponse)
async def get_trace(
    trace_id: str,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> PersistedTrace:
    trace = await db_session.scalar(
        select(PersistedTrace).where(
            PersistedTrace.trace_id == trace_id,
            PersistedTrace.organization_id == access.actor.organization_id,
            PersistedTrace.project_id == access.project.id,
        )
    )
    if trace is None:
        raise _not_found()
    return trace


@router.get("/failures", response_model=list[FailureCaseResponse])
async def list_failure_cases(
    run_id: UUID | None = None,
    code: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[FailureCase]:
    query = select(FailureCase).where(
        FailureCase.organization_id == access.actor.organization_id,
        FailureCase.project_id == access.project.id,
    )
    if run_id is not None:
        query = query.where(FailureCase.run_id == run_id)
    if code is not None:
        query = query.where(FailureCase.code == code)
    return list(
        (await db_session.scalars(query.order_by(FailureCase.created_at.desc()).limit(limit))).all()
    )
