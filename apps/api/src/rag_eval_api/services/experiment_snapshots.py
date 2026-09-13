"""Deterministic, immutable experiment configuration snapshots."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ExperimentSnapshotInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version_id: UUID
    adapter_config_id: UUID
    adapter_version: str = Field(min_length=1, max_length=100)
    model_provider_id: UUID
    model_name: str = Field(min_length=1, max_length=255)
    metric_versions: dict[str, str] = Field(max_length=50)
    parameters: dict[str, object] = Field(max_length=100)
    random_seed: int
    environment: dict[str, str] = Field(max_length=50)


class ExperimentSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID
    dataset_version_id: UUID
    adapter_config_id: UUID
    adapter_version: str
    model_provider_id: UUID
    model_name: str
    metric_versions: dict[str, str]
    parameters: dict[str, object]
    random_seed: int
    environment_hash: str


def create_snapshot(payload: ExperimentSnapshotInput) -> ExperimentSnapshot:
    serialized = json.dumps(
        payload.environment, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    parameter_bytes = json.dumps(
        payload.parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(parameter_bytes) > 64 * 1024:
        raise ValueError("parameters must be at most 64 KiB")
    return ExperimentSnapshot(
        snapshot_id=uuid4(),
        dataset_version_id=payload.dataset_version_id,
        adapter_config_id=payload.adapter_config_id,
        adapter_version=payload.adapter_version,
        model_provider_id=payload.model_provider_id,
        model_name=payload.model_name,
        metric_versions=dict(payload.metric_versions),
        parameters=dict(payload.parameters),
        random_seed=payload.random_seed,
        environment_hash=hashlib.sha256(serialized).hexdigest(),
    )
