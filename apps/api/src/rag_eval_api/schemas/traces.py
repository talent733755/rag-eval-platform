"""Public Trace and failure diagnosis response contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TraceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    experiment_id: UUID
    run_id: UUID
    run_item_id: UUID
    trace_id: str
    trace_version: str
    level: str
    payload_hash: str
    stages: list[dict[str, object]]
    created_at: datetime


class FailureCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    experiment_id: UUID
    run_id: UUID
    run_item_id: UUID
    attempt_number: int
    code: str
    retryable: bool
    safe_message: str
    trace_id: str | None
    details: dict[str, object]
    created_at: datetime
