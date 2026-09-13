"""Candidate generation request and blocked-response schemas."""

from uuid import UUID

from pydantic import BaseModel, Field


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
