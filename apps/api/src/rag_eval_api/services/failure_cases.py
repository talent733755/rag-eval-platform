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
    retrieved_ids: list[str] | None = None,
    relevant_ids: list[str] | None = None,
) -> FailureCase | None:
    """Store only stable classification and safe context, never raw upstream errors."""

    timed_out = error_code in {"adapter_timeout", "timeout"}
    adapter_failure = error_code is not None and not timed_out
    relevant_retrieved: bool | None = None
    if relevant_ids and retrieved_ids:
        # An empty retrieved list means the trace carried no structured
        # retrieval evidence; we cannot attribute the failure to retrieval then.
        relevant_retrieved = bool(set(retrieved_ids) & set(relevant_ids))
    diagnosis = classify_failure(
        adapter_error=adapter_failure,
        timed_out=timed_out,
        relevant_retrieved=relevant_retrieved,
    )
    if diagnosis is None:
        return None
    details: dict[str, object] = {"source": "experiment_run_attempt"}
    if error_code is not None:
        details["error_code"] = error_code or "unknown"
    else:
        details["retrieved_count"] = len(retrieved_ids or [])
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
        details=details,
    )
    session.add(failure)
    await session.flush()
    return failure
