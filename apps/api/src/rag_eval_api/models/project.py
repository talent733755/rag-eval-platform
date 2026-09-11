"""Project model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_eval_api.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from rag_eval_api.models.audit_event import AuditEvent
    from rag_eval_api.models.candidates import (
        CandidateDataset,
        CandidateDatasetItem,
        CandidateGenerationConfig,
        CandidateItemEvidence,
    )
    from rag_eval_api.models.documents import Document, DocumentChunk, DocumentVersion
    from rag_eval_api.models.ingestion import IngestionJob, IngestionJobAttempt, IngestionJobLease
    from rag_eval_api.models.membership import Membership
    from rag_eval_api.models.organization import Organization


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A project scoped to exactly one organization."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_projects_id_organization_id"),
        UniqueConstraint("organization_id", "slug", name="uq_projects_organization_id_slug"),
        CheckConstraint("length(trim(name)) > 0", name="name_nonempty"),
        CheckConstraint("length(trim(slug)) > 0", name="slug_nonempty"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    memberships: Mapped[list[Membership]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        overlaps="organization,memberships",
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        back_populates="project",
        overlaps="organization,audit_events",
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="project", overlaps="organization,versions,latest_version,documents"
    )
    document_versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="project", overlaps="organization,document,chunks,document_versions"
    )
    document_chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="project",
        overlaps="organization,document_version,evidence,chunks,document_chunks",
    )
    candidate_datasets: Mapped[list[CandidateDataset]] = relationship(
        back_populates="project",
        overlaps="organization,generation_configs,items,candidate_datasets",
    )
    candidate_generation_configs: Mapped[list[CandidateGenerationConfig]] = relationship(
        back_populates="project",
        overlaps="organization,dataset,candidate_generation_configs,generation_configs",
    )
    candidate_dataset_items: Mapped[list[CandidateDatasetItem]] = relationship(
        back_populates="project",
        overlaps="organization,dataset,evidence,candidate_dataset_items,items",
    )
    candidate_item_evidence: Mapped[list[CandidateItemEvidence]] = relationship(
        back_populates="project",
        overlaps="organization,item,chunk,candidate_item_evidence,evidence",
    )
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="project",
        overlaps="organization,document_version,candidate_dataset,attempts,lease,ingestion_jobs",
    )
    ingestion_job_attempts: Mapped[list[IngestionJobAttempt]] = relationship(
        back_populates="project", overlaps="organization,job,attempts,ingestion_job_attempts"
    )
    ingestion_job_leases: Mapped[list[IngestionJobLease]] = relationship(
        back_populates="project", overlaps="organization,job,lease,ingestion_job_leases"
    )

    def __repr__(self) -> str:
        return (
            f"Project(id={self.id!r}, organization_id={self.organization_id!r}, slug={self.slug!r})"
        )
