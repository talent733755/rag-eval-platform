"""Tenant-scoped, append-only metric definitions and calculated results."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from rag_eval_api.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class MetricScope(str, Enum):
    run = "run"
    sample = "sample"


class MetricDefinition(UUIDPrimaryKeyMixin, Base):
    """An immutable, project-scoped metric definition and version."""

    __tablename__ = "metric_definitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_metric_definitions_project_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "project_id",
            "metric_key",
            "version",
            name="uq_metric_definitions_key_version",
        ),
        UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_metric_definitions_tenant"
        ),
        CheckConstraint("length(trim(metric_key)) > 0", name="metric_definition_key_nonempty"),
        CheckConstraint("length(trim(version)) > 0", name="metric_definition_version_nonempty"),
        Index("ix_metric_definitions_project_key", "organization_id", "project_id", "metric_key"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    definition: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default="CURRENT_TIMESTAMP"
    )


class MetricResult(UUIDPrimaryKeyMixin, Base):
    """An append-only aggregate or per-sample metric result."""

    __tablename__ = "metric_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["experiment_id", "organization_id", "project_id"],
            ["experiments.id", "experiments.organization_id", "experiments.project_id"],
            name="fk_metric_results_experiment_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "organization_id", "project_id"],
            ["experiment_runs.id", "experiment_runs.organization_id", "experiment_runs.project_id"],
            name="fk_metric_results_run_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_item_id", "organization_id", "project_id"],
            [
                "experiment_run_items.id",
                "experiment_run_items.organization_id",
                "experiment_run_items.project_id",
            ],
            name="fk_metric_results_item_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["metric_definition_id", "organization_id", "project_id"],
            [
                "metric_definitions.id",
                "metric_definitions.organization_id",
                "metric_definitions.project_id",
            ],
            name="fk_metric_results_definition_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "run_id",
            "scope_key",
            "metric_definition_id",
            name="uq_metric_results_run_scope_definition",
        ),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_metric_results_tenant"),
        CheckConstraint(
            "(scope = 'run' AND run_item_id IS NULL AND scope_key = 'run') OR "
            "(scope = 'sample' AND run_item_id IS NOT NULL AND scope_key <> 'run')",
            name="metric_result_scope_shape",
        ),
        CheckConstraint("sample_count >= 0", name="metric_result_sample_count_nonnegative"),
        Index("ix_metric_results_run_metric", "run_id", "metric_definition_id", "scope"),
        Index("ix_metric_results_item", "run_item_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    experiment_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_item_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    metric_definition_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[MetricScope] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    numerator: Mapped[float | None] = mapped_column(Float, nullable=True)
    denominator: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dimensions: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    distribution: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default="CURRENT_TIMESTAMP"
    )


@event.listens_for(MetricDefinition, "before_update")
def _prevent_metric_definition_update(
    mapper: object, connection: object, target: MetricDefinition
) -> None:
    del mapper, connection, target
    raise ValueError("MetricDefinition records are immutable versions")


@event.listens_for(MetricDefinition, "before_delete")
def _prevent_metric_definition_delete(
    mapper: object, connection: object, target: MetricDefinition
) -> None:
    del mapper, connection, target
    raise ValueError("MetricDefinition records are immutable versions")


@event.listens_for(MetricResult, "before_update")
def _prevent_metric_result_update(mapper: object, connection: object, target: MetricResult) -> None:
    del mapper, connection, target
    raise ValueError("MetricResult records are append-only")


@event.listens_for(MetricResult, "before_delete")
def _prevent_metric_result_delete(mapper: object, connection: object, target: MetricResult) -> None:
    del mapper, connection, target
    raise ValueError("MetricResult records are append-only")
