"""Safe, append-only persistence for primary failure diagnoses."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.models import FailureCase
from rag_eval_api.services.failure_diagnosis import classify_failure


async def persist_failure_case(
    session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    experiment_id: UUID,
    run_id: UUID,
    run_item_id: UUID,
    attempt_number: int,
    error_code: str | None,
    trace_id: str | None,
) -> FailureCase | None:
    """Store only stable classification and safe context, never raw upstream errors."""

    timed_out = error_code in {"adapter_timeout", "timeout"}
    diagnosis = classify_failure(adapter_error=not timed_out, timed_out=timed_out)
    if diagnosis is None:
        return None
    failure = FailureCase(
        organization_id=organization_id,
        project_id=project_id,
        experiment_id=experiment_id,
        run_id=run_id,
        run_item_id=run_item_id,
        attempt_number=attempt_number,
        code=diagnosis.code,
        retryable=diagnosis.retryable,
        safe_message=diagnosis.safe_message,
        trace_id=trace_id,
        details={"source": "experiment_run_attempt", "error_code": error_code or "unknown"},
    )
    session.add(failure)
    await session.flush()
    return failure
