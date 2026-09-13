"""Candidate generation request and blocked-response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CandidateGenerationRequest(BaseModel):
    document_version_id: UUID
    dataset_name: str = Field(min_length=1, max_length=255)
    capability_version: str = Field(pattern=r"^candidate-generation-v1$")
    prompt_version: str = Field(min_length=1, max_length=100)
    seed: int | None = None
    randomness: float = Field(ge=0, le=2)


class CandidateGenerationBlockedResponse(BaseModel):
    code: str
    message: str


class CandidateGenerationJobResponse(BaseModel):
    job_id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    status: str


class CandidateDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    description: str | None
    status: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CandidateDatasetVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    organization_id: UUID
    project_id: UUID
    version_number: int
    status: str
    item_count: int
    source_snapshot_hash: str | None
    published_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class CandidateEvidenceResponse(BaseModel):
    id: UUID
    source_version_id: UUID
    chunk_id: UUID
    ordinal: int
    excerpt: str | None


class CandidateItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    dataset_version_id: UUID | None
    source_version_id: UUID
    question: str
    question_type: str
    difficulty: str | None
    reference_answer: str
    confidence: float
    automatic_checks: dict[str, object]
    review_status: str
    provenance: dict[str, object]
    evidence: list[CandidateEvidenceResponse]


class CandidateReviewRequest(BaseModel):
    item_id: UUID
    review_status: Literal["accepted", "rejected", "pending"]
    comment: str | None = Field(default=None, max_length=2000)
