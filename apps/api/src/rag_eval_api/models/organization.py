"""Organization model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_eval_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

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
    from rag_eval_api.models.project import Project


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant boundary for projects, memberships, and audit events."""

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
        CheckConstraint("length(trim(name)) > 0", name="name_nonempty"),
        CheckConstraint("length(trim(slug)) > 0", name="slug_nonempty"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)

    projects: Mapped[list[Project]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        overlaps="project,organization",
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        back_populates="organization",
        overlaps="project,audit_events",
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="organization", overlaps="project,versions,latest_version"
    )
    document_versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="organization", overlaps="project,document,chunks"
    )
    document_chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="organization", overlaps="project,document_version,evidence,chunks"
    )
    candidate_datasets: Mapped[list[CandidateDataset]] = relationship(
        back_populates="organization", overlaps="project,generation_configs,items"
    )
    candidate_generation_configs: Mapped[list[CandidateGenerationConfig]] = relationship(
        back_populates="organization", overlaps="project,dataset,generation_configs"
    )
    candidate_dataset_items: Mapped[list[CandidateDatasetItem]] = relationship(
        back_populates="organization", overlaps="project,dataset,evidence,items"
    )
    candidate_item_evidence: Mapped[list[CandidateItemEvidence]] = relationship(
        back_populates="organization", overlaps="project,item,chunk,evidence"
    )
    ingestion_jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="organization",
        overlaps="project,document_version,candidate_dataset,attempts,lease",
    )
    ingestion_job_attempts: Mapped[list[IngestionJobAttempt]] = relationship(
        back_populates="organization", overlaps="project,job,attempts"
    )
    ingestion_job_leases: Mapped[list[IngestionJobLease]] = relationship(
        back_populates="organization", overlaps="project,job,lease"
    )

    def __repr__(self) -> str:
        return f"Organization(id={self.id!r}, slug={self.slug!r})"
