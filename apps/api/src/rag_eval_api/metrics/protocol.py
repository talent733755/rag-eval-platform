"""Versioned metric input/output contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RetrievalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieved_ids: list[str] = Field(default_factory=list, max_length=1000)
    relevant_ids: list[str] = Field(default_factory=list, max_length=1000)
    k: int = Field(gt=0, le=1000)

    @field_validator("retrieved_ids", "relevant_ids")
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("metric IDs must be non-empty")
        return value


class MetricResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    # Retrieval metrics are bounded, while engineering metrics such as
    # latency and token counts use their natural units.
    value: float | None = Field(default=None)
    sample_count: int = Field(ge=0)
    missing_reason: str | None = None
    provenance: dict[str, str] = Field(default_factory=dict)
