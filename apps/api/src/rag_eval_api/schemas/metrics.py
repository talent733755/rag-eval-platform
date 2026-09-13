"""Public metric definition and result response contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MetricDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    metric_key: str
    version: str
    name: str
    description: str
    stage: str
    definition: dict[str, object]
    created_by: UUID
    created_at: datetime


class MetricResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    experiment_id: UUID
    run_id: UUID
    run_item_id: UUID | None
    metric_definition_id: UUID
    metric_key: str
    metric_version: str
    scope: str
    scope_key: str
    value: float | None
    numerator: float | None
    denominator: float | None
    sample_count: int
    missing_reason: str | None
    dimensions: dict[str, object]
    distribution: dict[str, object]
    provenance: dict[str, object]
    created_at: datetime
