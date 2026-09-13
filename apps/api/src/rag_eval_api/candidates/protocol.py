"""Provider-neutral candidate generation protocol."""

from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

CAPABILITY_VERSION = "candidate-generation-v1"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class CandidateChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    ordinal: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=50_000)
    content_hash: Annotated[str, StringConstraints(pattern=SHA256_PATTERN)]
    source_location: dict[str, object] = Field(default_factory=dict)


class CandidateGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_version_id: UUID
    dataset_name: str = Field(min_length=1, max_length=255)
    capability_version: str
    parser_version: str | None = Field(default=None, min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    check_rules_version: str | None = Field(default=None, min_length=1, max_length=100)
    seed: int | None = None
    randomness: float = Field(ge=0, le=2)
    chunks: tuple[CandidateChunk, ...] = Field(min_length=1, max_length=10_000)
    request_id: str = Field(min_length=1, max_length=255)

    @field_validator("capability_version")
    @classmethod
    def validate_capability_version(cls, value: str) -> str:
        if value != CAPABILITY_VERSION:
            raise ValueError(f"capability_version must be {CAPABILITY_VERSION}")
        return value

    @model_validator(mode="after")
    def validate_chunk_snapshot(self) -> CandidateGenerationRequest:
        ordinals = [chunk.ordinal for chunk in self.chunks]
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("chunks must not contain duplicate ordinals")
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("chunks must not contain duplicate chunk ids")
        return self


class CandidateEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_version_id: UUID
    chunk_id: UUID
    ordinal: int = Field(ge=0)
    excerpt: str = Field(min_length=1, max_length=10_000)


class CandidateItemDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_version_id: UUID
    question: str = Field(min_length=1, max_length=10_000)
    question_type: str = Field(min_length=1, max_length=100)
    reference_answer: str = Field(min_length=1, max_length=20_000)
    confidence: float = Field(ge=0, le=1)
    automatic_checks: dict[str, object]
    evidence: tuple[CandidateEvidence, ...] = Field(min_length=1, max_length=100)
    provenance: dict[str, object]

    @model_validator(mode="after")
    def validate_evidence_version(self) -> CandidateItemDraft:
        if any(item.source_version_id != self.source_version_id for item in self.evidence):
            raise ValueError("candidate evidence must reference the candidate source version")
        return self


class UsageSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0, ge=0)


class CandidateGenerationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability_version: str
    provider_name: str = Field(min_length=1, max_length=100)
    items: tuple[CandidateItemDraft, ...] = Field(min_length=1, max_length=10_000)
    usage: UsageSnapshot = Field(default_factory=UsageSnapshot)
    provenance: dict[str, object]

    @field_validator("capability_version")
    @classmethod
    def validate_result_capability(cls, value: str) -> str:
        if value != CAPABILITY_VERSION:
            raise ValueError(f"capability_version must be {CAPABILITY_VERSION}")
        return value


class GenerationFailure(Exception):
    """Stable, safe-to-display generation failure."""

    _MESSAGES = {
        "provider_not_configured": "No candidate generation provider is configured.",
        "provider_timeout": "The candidate generation provider timed out.",
        "invalid_provider_output": "The candidate generation provider returned invalid data.",
    }

    def __init__(self, *, code: str, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        self.safe_message = self._MESSAGES.get(code, "Candidate generation failed safely.")
        super().__init__(self.safe_message)


class CandidateGenerator(Protocol):
    """Stable provider boundary used by the candidate generation service."""

    def generate(
        self,
        request: CandidateGenerationRequest,
        cancel_token: object | None = None,
    ) -> CandidateGenerationResult: ...
