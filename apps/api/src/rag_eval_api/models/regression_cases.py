"""Immutable regression cases copied from diagnosed evaluation failures."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from rag_eval_api.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class RegressionCaseStatus(str, Enum):
    active = "active"
    archived = "archived"


class RegressionCase(UUIDPrimaryKeyMixin, Base):
    """An immutable regression fixture retaining its source lineage."""

    __tablename__ = "regression_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["failure_case_id", "organization_id", "project_id"],
            ["failure_cases.id", "failure_cases.organization_id", "failure_cases.project_id"],
            name="fk_regression_cases_failure_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_item_id", "organization_id", "project_id"],
            [
                "experiment_run_items.id",
                "experiment_run_items.organization_id",
                "experiment_run_items.project_id",
            ],
            name="fk_regression_cases_item_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_item_id", "organization_id", "project_id"],
            [
                "candidate_dataset_items.id",
                "candidate_dataset_items.organization_id",
                "candidate_dataset_items.project_id",
            ],
            name="fk_regression_cases_candidate_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["dataset_version_id", "organization_id", "project_id"],
            [
                "candidate_dataset_versions.id",
                "candidate_dataset_versions.organization_id",
                "candidate_dataset_versions.project_id",
            ],
            name="fk_regression_cases_dataset_version_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["trace_record_id", "organization_id", "project_id"],
            ["traces.id", "traces.organization_id", "traces.project_id"],
            name="fk_regression_cases_trace_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_regression_cases_project_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id", "project_id", "failure_case_id", name="uq_regression_cases_failure"
        ),
        UniqueConstraint(
            "organization_id",
            "project_id",
            "idempotency_key",
            name="uq_regression_cases_idempotency",
        ),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_regression_cases_tenant"),
        Index("ix_regression_cases_project_status", "organization_id", "project_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    failure_case_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_item_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    candidate_item_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    dataset_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    trace_record_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RegressionCaseStatus] = mapped_column(
        SqlEnum(RegressionCaseStatus, name="regression_case_status", native_enum=False),
        nullable=False,
        default=RegressionCaseStatus.active,
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


@event.listens_for(RegressionCase, "before_update")
def _reject_regression_case_update(
    mapper: object, connection: object, target: RegressionCase
) -> None:
    del mapper, connection, target
    raise ValueError("RegressionCase records are immutable")


@event.listens_for(RegressionCase, "before_delete")
def _reject_regression_case_delete(
    mapper: object, connection: object, target: RegressionCase
) -> None:
    del mapper, connection, target
    raise ValueError("RegressionCase records are immutable")
