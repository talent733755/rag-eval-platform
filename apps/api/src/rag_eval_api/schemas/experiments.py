"""Experiment draft validation contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExperimentDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    dataset_version_id: UUID
    adapter_config_id: UUID
    model_provider_id: UUID
    metric_versions: dict[str, str] = Field(max_length=50)
    parameters: dict[str, object] = Field(default_factory=dict, max_length=100)
    random_seed: int | None = None


class ValidatedExperimentDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    dataset_version_id: UUID
    dataset_item_count: int
    adapter_config_id: UUID
    adapter_version: str
    model_provider_id: UUID
    model_name: str
    metric_versions: dict[str, str]
    parameters: dict[str, object]
    random_seed: int


class ExperimentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    experiment_id: UUID
    status: str
    total_units: int
    completed_units: int
    succeeded_units: int
    failed_units: int
    skipped_units: int
    created_by: UUID
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExperimentRunItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    candidate_item_id: UUID
    status: str
    attempt_count: int
    final_answer: str | None
    final_usage: dict[str, object] | None
    final_latency_ms: int | None
    final_trace_id: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    status: str
    dataset_version_id: UUID
    adapter_config_id: UUID
    model_provider_id: UUID
    metric_versions: dict[str, str]
    parameters: dict[str, object]
    random_seed: int
    configuration_snapshot: dict[str, object]
    environment_hash: str
    total_units: int
    completed_units: int
    succeeded_units: int
    failed_units: int
    skipped_units: int
    created_by: UUID
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExperimentStartResponse(BaseModel):
    experiment: ExperimentResponse
    run: ExperimentRunResponse
