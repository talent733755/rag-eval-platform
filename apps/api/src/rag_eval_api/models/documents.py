"""Tenant-scoped document, immutable version, and parsed chunk models."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    inspect,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_eval_api.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from rag_eval_api.models.candidates import CandidateItemEvidence
    from rag_eval_api.models.organization import Organization
    from rag_eval_api.models.project import Project


class DocumentSourceType(str, Enum):
    """Supported source categories; parser implementations are added later."""

    pdf = "pdf"
    docx = "docx"
    markdown = "markdown"
    txt = "txt"


class DocumentParseStatus(str, Enum):
    """Current parse state of a document version."""

    queued = "queued"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Logical document identity; bytes are stored on document versions."""

    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_documents_project_organization_projects",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["latest_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_documents_latest_version",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_documents_tenant_identity"
        ),
        CheckConstraint("length(trim(display_name)) > 0", name="display_name_nonempty"),
        Index("ix_documents_project_updated_at", "organization_id", "project_id", "updated_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[DocumentSourceType] = mapped_column(
        SqlEnum(
            DocumentSourceType,
            name="document_source_type",
            native_enum=False,
            create_constraint=True,
            length=8,
        ),
        nullable=False,
    )
    latest_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    organization: Mapped[Organization] = relationship(
        back_populates="documents", overlaps="project,versions,latest_version"
    )
    project: Mapped[Project] = relationship(
        back_populates="documents", overlaps="organization,versions,latest_version"
    )
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        foreign_keys="DocumentVersion.document_id",
        cascade="save-update, merge",
        passive_deletes=True,
        overlaps="organization,project,latest_version",
    )
    latest_version: Mapped[DocumentVersion | None] = relationship(
        foreign_keys=[latest_version_id],
        primaryjoin="Document.latest_version_id == DocumentVersion.id",
        post_update=True,
        viewonly=True,
        overlaps="organization,project,versions",
    )


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An immutable uploaded byte-set with mutable parse outcome metadata."""

    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id", "project_id"],
            ["documents.id", "documents.organization_id", "documents.project_id"],
            name="fk_document_versions_document_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_document_versions_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_document_versions_tenant_identity"
        ),
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_version_number"
        ),
        UniqueConstraint(
            "organization_id",
            "project_id",
            "sha256",
            "byte_size",
            name="uq_document_versions_project_content_identity",
        ),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("length(sha256) = 64", name="sha256_length_64"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_lower_hex_64").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint("parsed_character_count >= 0", name="parsed_character_count_nonnegative"),
        CheckConstraint("page_count >= 0", name="page_count_nonnegative"),
        Index(
            "ix_document_versions_project_status", "organization_id", "project_id", "parse_status"
        ),
        Index("ix_document_versions_document_created_at", "document_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    detected_mime: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parse_status: Mapped[DocumentParseStatus] = mapped_column(
        SqlEnum(
            DocumentParseStatus,
            name="document_parse_status",
            native_enum=False,
            create_constraint=True,
            length=10,
        ),
        nullable=False,
    )
    parse_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parse_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_character_count: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    page_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")

    organization: Mapped[Organization] = relationship(
        back_populates="document_versions", overlaps="project,document,chunks"
    )
    project: Mapped[Project] = relationship(
        back_populates="document_versions", overlaps="organization,document,chunks"
    )
    document: Mapped[Document] = relationship(
        back_populates="versions",
        foreign_keys=[document_id],
        overlaps="organization,project,chunks",
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document_version",
        cascade="save-update, merge",
        passive_deletes=True,
        overlaps="organization,project,document",
    )


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IMMUTABLE_VERSION_FIELDS = (
    "document_id",
    "version_number",
    "sha256",
    "byte_size",
    "detected_mime",
    "storage_key",
)


def _validate_sha256(value: str, field_name: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be exactly 64 lowercase hexadecimal characters")


@event.listens_for(DocumentVersion, "before_insert")
def _validate_document_version_insert(
    mapper: object, connection: object, target: DocumentVersion
) -> None:
    del mapper, connection
    _validate_sha256(target.sha256, "sha256")


@event.listens_for(DocumentVersion, "before_update")
def _protect_document_version_bytes(
    mapper: object, connection: object, target: DocumentVersion
) -> None:
    del mapper, connection
    state = inspect(target)
    if any(state.attrs[field].history.has_changes() for field in _IMMUTABLE_VERSION_FIELDS):
        raise ValueError("document version source bytes metadata is immutable")
    _validate_sha256(target.sha256, "sha256")


@event.listens_for(DocumentVersion, "before_delete")
def _reject_document_version_delete(
    mapper: object, connection: object, target: DocumentVersion
) -> None:
    del mapper, connection, target
    raise ValueError("DocumentVersion records are retained and cannot be deleted")


class DocumentChunk(UUIDPrimaryKeyMixin, Base):
    """A normalized, source-locatable chunk produced by a parser."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_document_chunks_version_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_document_chunks_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_document_chunks_tenant_identity"
        ),
        UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_chunks_version_ordinal"
        ),
        UniqueConstraint(
            "id",
            "document_version_id",
            "organization_id",
            "project_id",
            name="uq_document_chunks_version_tenant_identity",
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_length_64"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_lower_hex_64").ddl_if(
            dialect="postgresql"
        ),
        CheckConstraint("character_count >= 0", name="character_count_nonnegative"),
        CheckConstraint("token_count >= 0", name="token_count_nonnegative"),
        Index(
            "ix_document_chunks_project_version",
            "organization_id",
            "project_id",
            "document_version_id",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    document_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    paragraph_index: Mapped[int | None] = mapped_column(nullable=True)
    source_location: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    character_count: Mapped[int] = mapped_column(nullable=False)
    token_count: Mapped[int] = mapped_column(nullable=False)

    organization: Mapped[Organization] = relationship(
        back_populates="document_chunks", overlaps="project,document_version,evidence"
    )
    project: Mapped[Project] = relationship(
        back_populates="document_chunks", overlaps="organization,document_version,evidence"
    )
    document_version: Mapped[DocumentVersion] = relationship(
        back_populates="chunks", overlaps="organization,project,evidence"
    )
    evidence: Mapped[list[CandidateItemEvidence]] = relationship(
        back_populates="chunk",
        passive_deletes=True,
        overlaps="organization,project,document_version,evidence,item",
    )


@event.listens_for(DocumentChunk, "before_insert")
def _validate_document_chunk_insert(
    mapper: object, connection: object, target: DocumentChunk
) -> None:
    del mapper, connection
    _validate_sha256(target.content_hash, "content_hash")


@event.listens_for(DocumentChunk, "before_update")
def _reject_chunk_update(mapper: object, connection: object, target: DocumentChunk) -> None:
    del mapper, connection, target
    raise ValueError("DocumentChunk records are append-only")


@event.listens_for(DocumentChunk, "before_delete")
def _reject_chunk_delete(mapper: object, connection: object, target: DocumentChunk) -> None:
    del mapper, connection, target
    raise ValueError("DocumentChunk records are append-only")
