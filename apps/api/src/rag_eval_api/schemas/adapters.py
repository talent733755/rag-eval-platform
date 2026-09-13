"""Public adapter configuration schemas without credential material."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdapterConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["http", "python"]
    endpoint: str | None = Field(default=None, max_length=2048)
    credential_ref: str | None = Field(default=None, min_length=1, max_length=255)
    entrypoint_ref: str | None = Field(default=None, min_length=1, max_length=255)
    adapter_version: str = Field(min_length=1, max_length=100)
    trace_level: Literal["none", "minimal", "full"] = "minimal"
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    retry_count: int = Field(default=0, ge=0, le=5)
    enabled: bool = False


class AdapterConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: Literal["http", "python"] | None = None
    endpoint: str | None = Field(default=None, max_length=2048)
    credential_ref: str | None = Field(default=None, min_length=1, max_length=255)
    entrypoint_ref: str | None = Field(default=None, min_length=1, max_length=255)
    adapter_version: str | None = Field(default=None, min_length=1, max_length=100)
    trace_level: Literal["none", "minimal", "full"] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    retry_count: int | None = Field(default=None, ge=0, le=5)
    enabled: bool | None = None


class AdapterConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    name: str
    kind: str
    endpoint: str | None
    credential_ref: str | None
    entrypoint_ref: str | None
    token_last4: str | None
    adapter_version: str
    trace_level: str
    timeout_seconds: float
    retry_count: int
    enabled: bool
    last_test_status: str
    created_at: datetime
