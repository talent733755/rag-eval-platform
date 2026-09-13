"""Provider-neutral RAG adapter contract.

The protocol is deliberately independent of FastAPI, SQLAlchemy, and any
vendor SDK. Implementations may be HTTP or Python entry points, but both must
return the same validated response shape.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

ADAPTER_CAPABILITY_VERSION = "adapter-v1"


class AdapterCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_version: str = Field(pattern=r"^adapter-v1$")
    adapter_version: str = Field(min_length=1, max_length=100)
    trace_level: str = Field(pattern=r"^(none|minimal|full)$")
    supports_batch: bool = False


class AdapterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=255)
    question: str = Field(min_length=1, max_length=20_000)
    context: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=32)
    timeout_seconds: float = Field(gt=0, le=300)

    @field_validator("context")
    @classmethod
    def validate_context(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 50_000 for item in value):
            raise ValueError("context entries must be non-empty and at most 50000 characters")
        return value


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=255)
    chunk_id: str = Field(min_length=1, max_length=255)
    ordinal: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=10_000)
    score: float | None = Field(default=None, ge=0, le=1)


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)


class TraceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1, max_length=255)
    level: str = Field(pattern=r"^(none|minimal|full)$")
    stages: dict[str, dict[str, object]] = Field(default_factory=dict, max_length=32)


class AdapterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=255)
    answer: str = Field(min_length=1, max_length=100_000)
    citations: list[Citation] = Field(default_factory=list, max_length=100)
    usage: Usage
    trace: TraceEnvelope | None = None


class Adapter(Protocol):
    """Minimal synchronous boundary used by the experiment executor."""

    capability: AdapterCapability

    def run(self, request: AdapterRequest) -> AdapterResponse:
        """Execute one bounded evaluation request."""
