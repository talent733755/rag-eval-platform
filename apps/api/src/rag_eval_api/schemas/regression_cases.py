"""Regression case API contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RegressionCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_case_id: UUID
    title: str = Field(min_length=1, max_length=255)
    notes: str | None = Field(default=None, max_length=2_000)


class RegressionCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    failure_case_id: UUID
    run_item_id: UUID
    candidate_item_id: UUID
    dataset_version_id: UUID
    trace_record_id: UUID | None
    trace_id: str | None
    idempotency_key: str
    title: str
    notes: str | None
    status: str
    created_by: UUID
    created_at: datetime
