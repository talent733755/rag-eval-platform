"""Experiment draft validation contracts."""

from __future__ import annotations

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
