"""Project and membership API schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rag_eval_api.models import MembershipRole

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _strip_nonempty(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be empty")
    return stripped


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=10_000)

    @field_validator("name", "slug")
    @classmethod
    def validate_names(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        return _strip_nonempty(value, str(field_name))


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    user_id: UUID
    role: MembershipRole
    created_at: datetime
    updated_at: datetime


class MemberInviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: MembershipRole

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("email must be valid")
        return normalized


class MemberInviteResponse(BaseModel):
    project_id: UUID
    email: str
    role: MembershipRole
    status: Literal["pending"]


class MemberRoleUpdate(BaseModel):
    role: MembershipRole
