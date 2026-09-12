"""Typed public value objects used by the document ingestion contract."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DocumentContentIdentity(BaseModel):
    """The project-scoped content identity used for duplicate detection."""

    sha256: Sha256Hex
    byte_size: int = Field(gt=0)


class DocumentUploadDocument(BaseModel):
    """Stable logical-document fields returned after an upload is queued."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    display_name: str
    source_type: str
    latest_version_id: UUID
    archived_at: datetime | None


class DocumentUploadVersion(BaseModel):
    """Stable immutable source-version fields returned after an upload."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    version_number: int
    sha256: Sha256Hex
    byte_size: int = Field(gt=0)
    detected_mime: str
    storage_key: str
    parse_status: str
    parser_version: str | None
    parse_error_code: str | None


class DocumentUploadJob(BaseModel):
    """Stable queued parse-job fields returned after an upload."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    job_kind: str
    status: str
    document_version_id: UUID
    idempotency_key: str


class DocumentUploadResponse(BaseModel):
    """The 202 response for a successfully queued document upload."""

    document: DocumentUploadDocument
    document_version: DocumentUploadVersion
    ingestion_job: DocumentUploadJob


class DocumentVersionResponse(DocumentUploadVersion):
    """Public immutable document-version details without storage internals."""

    created_at: datetime
    updated_at: datetime
    parsed_character_count: int = Field(ge=0)
    page_count: int = Field(ge=0)


class DocumentResponse(BaseModel):
    """Tenant-scoped logical document with its latest version summary."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    display_name: str
    source_type: str
    latest_version_id: UUID | None
    archived_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    latest_version: DocumentVersionResponse | None


class DocumentListResponse(BaseModel):
    """Bounded, cursor-paginated document collection."""

    items: list[DocumentResponse]
    next_cursor: str | None
    summary: dict[str, int]


class DocumentVersionListResponse(BaseModel):
    """Version collection for one logical document."""

    items: list[DocumentVersionResponse]
    next_cursor: str | None


class DocumentJobResponse(BaseModel):
    """Safe job polling payload with no raw parser/provider error text."""

    id: UUID
    organization_id: UUID
    project_id: UUID
    job_kind: str
    status: str
    document_version_id: UUID | None
    candidate_dataset_id: UUID | None
    idempotency_key: str
    attempt_count: int = Field(ge=0)
    completed_units: int = Field(ge=0)
    total_units: int = Field(ge=0)
    cancel_requested_at: datetime | None
    last_error_code: str | None
