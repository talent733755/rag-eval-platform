"""Durable ingestion job, attempt history, and mutable lease models."""

from __future__ import annotations

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
    event,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_eval_api.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, utc_now

if TYPE_CHECKING:
    from rag_eval_api.models.candidates import CandidateDataset
    from rag_eval_api.models.documents import DocumentVersion
    from rag_eval_api.models.organization import Organization
    from rag_eval_api.models.project import Project


class IngestionJobKind(str, Enum):
    parse = "parse"
    generate_candidates = "generate_candidates"


class IngestionJobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    blocked = "blocked"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"


class IngestionAttemptFinalStatus(str, Enum):
    """Terminal outcomes persisted in append-only attempt history."""

    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"
    blocked = "blocked"
    cancelled = "cancelled"


class IngestionJob(UUIDPrimaryKeyMixin, Base):
    """A durable unit of parsing or candidate generation work."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_ingestion_jobs_project_organization_projects",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_ingestion_jobs_document_version_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_dataset_id", "organization_id", "project_id"],
            [
                "candidate_datasets.id",
                "candidate_datasets.organization_id",
                "candidate_datasets.project_id",
            ],
            name="fk_ingestion_jobs_candidate_dataset_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "project_id",
            "job_kind",
            "idempotency_key",
            name="uq_ingestion_jobs_project_operation_idempotency",
        ),
        UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_ingestion_jobs_tenant_identity"
        ),
        CheckConstraint(
            "((job_kind = 'parse' AND document_version_id IS NOT NULL AND candidate_dataset_id IS NULL) "
            "OR (job_kind = 'generate_candidates' AND document_version_id IS NULL AND candidate_dataset_id IS NOT NULL))",
            name="job_resource_matches_kind",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("completed_units >= 0", name="completed_units_nonnegative"),
        CheckConstraint("total_units >= 0", name="total_units_nonnegative"),
        Index(
            "ix_ingestion_jobs_project_status_created",
            "organization_id",
            "project_id",
            "status",
            "created_at",
        ),
        Index("ix_ingestion_jobs_status_updated", "status", "updated_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    job_kind: Mapped[IngestionJobKind] = mapped_column(
        SqlEnum(
            IngestionJobKind, name="ingestion_job_kind", native_enum=False, create_constraint=True
        ),
        nullable=False,
    )
    status: Mapped[IngestionJobStatus] = mapped_column(
        SqlEnum(
            IngestionJobStatus,
            name="ingestion_job_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )
    document_version_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    candidate_dataset_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    completed_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    total_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default="CURRENT_TIMESTAMP"
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default="CURRENT_TIMESTAMP",
    )

    organization: Mapped[Organization] = relationship(
        back_populates="ingestion_jobs", overlaps="project,document_version,candidate_dataset,attempts,lease"
    )
    project: Mapped[Project] = relationship(
        back_populates="ingestion_jobs", overlaps="organization,document_version,candidate_dataset,attempts,lease"
    )
    document_version: Mapped[DocumentVersion | None] = relationship(
        overlaps="organization,project,attempts,lease"
    )
    candidate_dataset: Mapped[CandidateDataset | None] = relationship(
        overlaps="organization,project,document_version,attempts,lease"
    )
    attempts: Mapped[list[IngestionJobAttempt]] = relationship(
        back_populates="job", cascade="save-update, merge", passive_deletes=True,
        overlaps="organization,project,document_version,candidate_dataset,lease",
    )
    lease: Mapped[IngestionJobLease | None] = relationship(
        back_populates="job", uselist=False, cascade="save-update, merge", passive_deletes=True,
        overlaps="organization,project,document_version,candidate_dataset,attempts",
    )


class IngestionJobAttempt(UUIDPrimaryKeyMixin, Base):
    """Append-only final history for one execution attempt."""

    __tablename__ = "ingestion_job_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "organization_id", "project_id"],
            ["ingestion_jobs.id", "ingestion_jobs.organization_id", "ingestion_jobs.project_id"],
            name="fk_ingestion_job_attempts_job_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_ingestion_job_attempts_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint("job_id", "attempt_number", name="uq_ingestion_job_attempts_job_number"),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint("fencing_token > 0", name="fencing_token_positive"),
        Index(
            "ix_ingestion_job_attempts_project_finished",
            "organization_id",
            "project_id",
            "finished_at",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    job_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    final_status: Mapped[IngestionAttemptFinalStatus] = mapped_column(
        SqlEnum(
            IngestionAttemptFinalStatus,
            name="ingestion_attempt_final_status",
            native_enum=False,
            create_constraint=True,
            length=10,
        ),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retryable: Mapped[bool] = mapped_column(nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger(), nullable=False)

    organization: Mapped[Organization] = relationship(
        back_populates="ingestion_job_attempts", overlaps="project,job"
    )
    project: Mapped[Project] = relationship(
        back_populates="ingestion_job_attempts", overlaps="organization,job"
    )
    job: Mapped[IngestionJob] = relationship(
        back_populates="attempts", overlaps="organization,project"
    )


class IngestionJobLease(UUIDPrimaryKeyMixin, Base):
    """Mutable lease row used for heartbeat and fencing."""

    __tablename__ = "ingestion_job_leases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "organization_id", "project_id"],
            ["ingestion_jobs.id", "ingestion_jobs.organization_id", "ingestion_jobs.project_id"],
            name="fk_ingestion_job_leases_job_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_ingestion_job_leases_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint("job_id", name="uq_ingestion_job_leases_job"),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint("fencing_token > 0", name="fencing_token_positive"),
        Index("ix_ingestion_job_leases_lease_expires_at", "lease_expires_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    job_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default="CURRENT_TIMESTAMP",
    )

    organization: Mapped[Organization] = relationship(
        back_populates="ingestion_job_leases", overlaps="project,job"
    )
    project: Mapped[Project] = relationship(
        back_populates="ingestion_job_leases", overlaps="organization,job"
    )
    job: Mapped[IngestionJob] = relationship(
        back_populates="lease", overlaps="organization,project"
    )


@event.listens_for(IngestionJobAttempt, "before_update")
def _reject_attempt_update(mapper: object, connection: object, target: IngestionJobAttempt) -> None:
    del mapper, connection, target
    raise ValueError("IngestionJobAttempt records are append-only")


@event.listens_for(IngestionJobAttempt, "before_delete")
def _reject_attempt_delete(mapper: object, connection: object, target: IngestionJobAttempt) -> None:
    del mapper, connection, target
    raise ValueError("IngestionJobAttempt records are append-only")
