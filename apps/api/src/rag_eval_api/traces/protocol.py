"""Bounded immutable Trace v1 value objects."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

TRACE_VERSION = "trace-v1"
MAX_STAGE_PAYLOAD_BYTES = 64 * 1024


class TraceStage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    started_at: datetime
    finished_at: datetime | None = None
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, object] | None = None

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is not None and len(str(value).encode("utf-8")) > MAX_STAGE_PAYLOAD_BYTES:
            raise ValueError("trace stage payload exceeds the configured limit")
        return value


class TraceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_version: str = Field(pattern=r"^trace-v1$")
    trace_id: str = Field(min_length=1, max_length=255)
    run_item_id: str = Field(min_length=1, max_length=255)
    level: str = Field(pattern=r"^(minimal|full)$")
    stages: tuple[TraceStage, ...] = Field(max_length=32)

    @field_validator("stages")
    @classmethod
    def validate_stage_names(cls, value: tuple[TraceStage, ...]) -> tuple[TraceStage, ...]:
        names = [stage.name for stage in value]
        if len(names) != len(set(names)):
            raise ValueError("trace stage names must be unique")
        return value
