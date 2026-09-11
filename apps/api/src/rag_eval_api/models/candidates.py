"""Candidate dataset and provenance models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    JSON,
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

from rag_eval_api.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, utc_now

if TYPE_CHECKING:
    from rag_eval_api.models.documents import DocumentChunk
    from rag_eval_api.models.organization import Organization
    from rag_eval_api.models.project import Project


class CandidateDatasetStatus(str, Enum):
    draft = "draft"
    review = "review"
    published = "published"
    archived = "archived"


class CandidateReviewStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class CandidateDataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A project-scoped, reviewable candidate collection."""

    __tablename__ = "candidate_datasets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_candidate_datasets_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_candidate_datasets_tenant_identity"
        ),
        CheckConstraint("length(trim(name)) > 0", name="name_nonempty"),
        Index("ix_candidate_datasets_project_status", "organization_id", "project_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CandidateDatasetStatus] = mapped_column(
        SqlEnum(
            CandidateDatasetStatus,
            name="candidate_dataset_status",
            native_enum=False,
            create_constraint=True,
            length=9,
        ),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    organization: Mapped[Organization] = relationship(
        back_populates="candidate_datasets", overlaps="project,generation_configs,items"
    )
    project: Mapped[Project] = relationship(
        back_populates="candidate_datasets", overlaps="organization,generation_configs,items"
    )
    generation_configs: Mapped[list[CandidateGenerationConfig]] = relationship(
        back_populates="dataset",
        cascade="save-update, merge",
        passive_deletes=True,
        overlaps="organization,project,items",
    )
    items: Mapped[list[CandidateDatasetItem]] = relationship(
        back_populates="dataset",
        cascade="save-update, merge",
        passive_deletes=True,
        overlaps="organization,project,generation_configs,evidence",
    )


class CandidateGenerationConfig(UUIDPrimaryKeyMixin, Base):
    """Immutable generator configuration and provenance snapshot."""

    __tablename__ = "candidate_generation_configs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "organization_id", "project_id"],
            [
                "candidate_datasets.id",
                "candidate_datasets.organization_id",
                "candidate_datasets.project_id",
            ],
            name="fk_candidate_generation_configs_dataset_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_candidate_generation_configs_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            "project_id",
            name="uq_candidate_generation_configs_tenant_identity",
        ),
        UniqueConstraint(
            "id",
            "dataset_id",
            "organization_id",
            "project_id",
            name="uq_candidate_generation_configs_dataset_tenant_identity",
        ),
        CheckConstraint("length(trim(capability_version)) > 0", name="capability_version_nonempty"),
        CheckConstraint("randomness >= 0", name="randomness_nonnegative"),
        CheckConstraint("estimated_cost >= 0", name="estimated_cost_nonnegative"),
        CheckConstraint("actual_cost >= 0", name="actual_cost_nonnegative"),
        Index("ix_candidate_generation_configs_dataset_created_at", "dataset_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    dataset_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    capability_version: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    normalizer_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    check_rules_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seed: Mapped[int | None] = mapped_column(nullable=True)
    randomness: Mapped[float] = mapped_column(nullable=False, default=0, server_default="0")
    requested_version_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    chunk_content_hashes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    environment: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    request_id: Mapped[str] = mapped_column(String(255), nullable=False)
    usage: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    estimated_cost: Mapped[float] = mapped_column(nullable=False, default=0, server_default="0")
    actual_cost: Mapped[float] = mapped_column(nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default="CURRENT_TIMESTAMP"
    )

    organization: Mapped[Organization] = relationship(
        back_populates="candidate_generation_configs", overlaps="project,dataset"
    )
    project: Mapped[Project] = relationship(
        back_populates="candidate_generation_configs", overlaps="organization,dataset"
    )
    dataset: Mapped[CandidateDataset] = relationship(
        back_populates="generation_configs", overlaps="organization,project"
    )


@event.listens_for(CandidateGenerationConfig, "before_update")
def _reject_generation_config_update(
    mapper: object, connection: object, target: CandidateGenerationConfig
) -> None:
    del mapper, connection, target
    raise ValueError("CandidateGenerationConfig records are immutable snapshots")


@event.listens_for(CandidateGenerationConfig, "before_delete")
def _reject_generation_config_delete(
    mapper: object, connection: object, target: CandidateGenerationConfig
) -> None:
    del mapper, connection, target
    raise ValueError("CandidateGenerationConfig records are immutable snapshots")


class CandidateDatasetItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A generated candidate with review state and immutable provenance."""

    __tablename__ = "candidate_dataset_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "organization_id", "project_id"],
            [
                "candidate_datasets.id",
                "candidate_datasets.organization_id",
                "candidate_datasets.project_id",
            ],
            name="fk_candidate_dataset_items_dataset_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_candidate_dataset_items_source_version_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["generation_config_id", "dataset_id", "organization_id", "project_id"],
            [
                "candidate_generation_configs.id",
                "candidate_generation_configs.dataset_id",
                "candidate_generation_configs.organization_id",
                "candidate_generation_configs.project_id",
            ],
            name="fk_candidate_dataset_items_generation_config_dataset_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_candidate_dataset_items_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_candidate_dataset_items_tenant_identity"
        ),
        UniqueConstraint(
            "id",
            "source_version_id",
            "organization_id",
            "project_id",
            name="uq_candidate_dataset_items_source_version_tenant_identity",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_candidate_dataset_items_dataset_review", "dataset_id", "review_status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    dataset_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    generation_config_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(100), nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_answer: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    automatic_checks: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    review_status: Mapped[CandidateReviewStatus] = mapped_column(
        SqlEnum(
            CandidateReviewStatus,
            name="candidate_review_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )
    provenance: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    organization: Mapped[Organization] = relationship(
        back_populates="candidate_dataset_items", overlaps="project,dataset,evidence"
    )
    project: Mapped[Project] = relationship(
        back_populates="candidate_dataset_items", overlaps="organization,dataset,evidence"
    )
    dataset: Mapped[CandidateDataset] = relationship(
        back_populates="items", overlaps="organization,project,evidence"
    )
    generation_config: Mapped[CandidateGenerationConfig] = relationship(
        viewonly=True, overlaps="organization,project,dataset,evidence,items"
    )
    evidence: Mapped[list[CandidateItemEvidence]] = relationship(
        back_populates="item",
        cascade="save-update, merge",
        passive_deletes=True,
        overlaps="organization,project,dataset,chunk",
    )


class CandidateItemEvidence(UUIDPrimaryKeyMixin, Base):
    """Immutable links from a candidate item to source chunks."""

    __tablename__ = "candidate_item_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "source_version_id", "organization_id", "project_id"],
            [
                "candidate_dataset_items.id",
                "candidate_dataset_items.source_version_id",
                "candidate_dataset_items.organization_id",
                "candidate_dataset_items.project_id",
            ],
            name="fk_candidate_item_evidence_item_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_version_id", "organization_id", "project_id"],
            [
                "document_versions.id",
                "document_versions.organization_id",
                "document_versions.project_id",
            ],
            name="fk_candidate_item_evidence_source_version_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "source_version_id", "organization_id", "project_id"],
            [
                "document_chunks.id",
                "document_chunks.document_version_id",
                "document_chunks.organization_id",
                "document_chunks.project_id",
            ],
            name="fk_candidate_item_evidence_chunk_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_candidate_item_evidence_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "item_id", "chunk_id", "ordinal", name="uq_candidate_item_evidence_item_chunk_ordinal"
        ),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        Index(
            "ix_candidate_item_evidence_project_item", "organization_id", "project_id", "item_id"
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    item_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    chunk_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped[Organization] = relationship(
        back_populates="candidate_item_evidence", overlaps="project,item,chunk"
    )
    project: Mapped[Project] = relationship(
        back_populates="candidate_item_evidence", overlaps="organization,item,chunk"
    )
    item: Mapped[CandidateDatasetItem] = relationship(
        back_populates="evidence", overlaps="organization,project,chunk"
    )
    chunk: Mapped[DocumentChunk] = relationship(
        back_populates="evidence", overlaps="organization,project,item"
    )


@event.listens_for(CandidateItemEvidence, "before_update")
def _reject_evidence_update(
    mapper: object, connection: object, target: CandidateItemEvidence
) -> None:
    del mapper, connection, target
    raise ValueError("CandidateItemEvidence records are append-only")


@event.listens_for(CandidateItemEvidence, "before_delete")
def _reject_evidence_delete(
    mapper: object, connection: object, target: CandidateItemEvidence
) -> None:
    del mapper, connection, target
    raise ValueError("CandidateItemEvidence records are append-only")
