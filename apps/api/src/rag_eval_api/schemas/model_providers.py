"""Public model provider schemas without API key material."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    endpoint: str = Field(min_length=1, max_length=2048)
    credential_ref: str = Field(min_length=1, max_length=255)
    model_name: str = Field(min_length=1, max_length=255)
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    enabled: bool = False


class ModelProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    endpoint: str
    credential_ref: str
    model_name: str
    timeout_seconds: float
    enabled: bool
    last_test_status: str
    created_at: datetime
