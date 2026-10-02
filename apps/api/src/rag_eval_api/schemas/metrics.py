"""Public metric definition and result response contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class QualityGateThresholdRequest(BaseModel):
    """A bound on one metric. At least one of min/max must be set."""

    model_config = ConfigDict(frozen=True)

    metric_key: str = Field(min_length=1, max_length=100)
    min_value: float | None = None
    max_value: float | None = None

    @model_validator(mode="after")
    def _bound_present(self) -> QualityGateThresholdRequest:
        if self.min_value is None and self.max_value is None:
            raise ValueError("a threshold must set min_value, max_value, or both")
        return self


class QualityGateRequest(BaseModel):
    """Deterministic threshold set evaluated against a run's aggregate metrics."""

    model_config = ConfigDict(frozen=True)

    thresholds: list[QualityGateThresholdRequest] = Field(min_length=1, max_length=50)
    missing_is_pass: bool = False


class QualityGateCheckResponse(BaseModel):
    metric_key: str
    passed: bool
    actual: float | None
    min_value: float | None
    max_value: float | None
    reason: str


class QualityGateResponse(BaseModel):
    run_id: UUID
    run_status: str
    passed: bool
    incomplete: bool
    checks: list[QualityGateCheckResponse]
