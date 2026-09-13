"""Immutable experiment configuration and recoverable run records."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
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
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from rag_eval_api.models.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class ExperimentStatus(str, Enum):
    draft = "draft"
    queued = "queued"
    running = "running"
    cancelling = "cancelling"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ExperimentRunStatus(str, Enum):
    queued = "queued"
    running = "running"
    cancelling = "cancelling"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ExperimentRunItemStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    skipped = "skipped"


class Experiment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A project-scoped experiment whose configuration is frozen at start."""

    __tablename__ = "experiments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_experiments_project_organization_projects",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["dataset_version_id", "organization_id", "project_id"],
            ["candidate_dataset_versions.id", "candidate_dataset_versions.organization_id", "candidate_dataset_versions.project_id"],
            name="fk_experiments_dataset_version_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["adapter_config_id", "organization_id", "project_id"],
            ["adapter_configs.id", "adapter_configs.organization_id", "adapter_configs.project_id"],
            name="fk_experiments_adapter_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["model_provider_id", "organization_id", "project_id"],
            ["model_provider_configs.id", "model_provider_configs.organization_id", "model_provider_configs.project_id"],
            name="fk_experiments_provider_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_experiments_tenant"),
        UniqueConstraint("organization_id", "project_id", "idempotency_key", name="uq_experiments_idempotency"),
        CheckConstraint("length(trim(name)) > 0", name="experiment_name_nonempty"),
        CheckConstraint("total_units >= 0 AND completed_units >= 0", name="experiment_units_nonnegative"),
        CheckConstraint("succeeded_units >= 0 AND failed_units >= 0 AND skipped_units >= 0", name="experiment_results_nonnegative"),
        Index("ix_experiments_project_status_created", "organization_id", "project_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ExperimentStatus] = mapped_column(SqlEnum(ExperimentStatus, name="experiment_status", native_enum=False, create_constraint=True), nullable=False, default=ExperimentStatus.draft)
    dataset_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    adapter_config_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    model_provider_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    metric_versions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    random_seed: Mapped[int] = mapped_column(nullable=False)
    configuration_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    environment_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    total_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    completed_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    succeeded_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    failed_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    skipped_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ExperimentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A recoverable execution record for one immutable experiment."""

    __tablename__ = "experiment_runs"
    __table_args__ = (
        ForeignKeyConstraint(["experiment_id", "organization_id", "project_id"], ["experiments.id", "experiments.organization_id", "experiments.project_id"], name="fk_experiment_runs_experiment_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["project_id", "organization_id"], ["projects.id", "projects.organization_id"], name="fk_experiment_runs_project_tenant", ondelete="CASCADE"),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_experiment_runs_tenant"),
        Index("ix_experiment_runs_project_status_created", "organization_id", "project_id", "status", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    experiment_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[ExperimentRunStatus] = mapped_column(SqlEnum(ExperimentRunStatus, name="experiment_run_status", native_enum=False, create_constraint=True), nullable=False, default=ExperimentRunStatus.queued)
    total_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    completed_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    succeeded_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    failed_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    skipped_units: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    fencing_token: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")


class ExperimentRunItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One candidate evaluation with independently recoverable state."""

    __tablename__ = "experiment_run_items"
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "organization_id", "project_id"], ["experiment_runs.id", "experiment_runs.organization_id", "experiment_runs.project_id"], name="fk_experiment_run_items_run_tenant", ondelete="CASCADE"),
        ForeignKeyConstraint(["candidate_item_id", "organization_id", "project_id"], ["candidate_dataset_items.id", "candidate_dataset_items.organization_id", "candidate_dataset_items.project_id"], name="fk_experiment_run_items_candidate_tenant", ondelete="RESTRICT"),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_experiment_run_items_tenant"),
        UniqueConstraint("run_id", "candidate_item_id", name="uq_experiment_run_items_candidate"),
        Index("ix_experiment_run_items_run_status", "run_id", "status"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    candidate_item_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[ExperimentRunItemStatus] = mapped_column(SqlEnum(ExperimentRunItemStatus, name="experiment_run_item_status", native_enum=False, create_constraint=True), nullable=False, default=ExperimentRunItemStatus.queued)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_usage: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    final_latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    final_trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ExperimentRunAttempt(UUIDPrimaryKeyMixin, Base):
    """Append-only attempt history for a run item."""

    __tablename__ = "experiment_run_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["run_item_id", "organization_id", "project_id"], ["experiment_run_items.id", "experiment_run_items.organization_id", "experiment_run_items.project_id"], name="fk_experiment_run_attempts_item_tenant", ondelete="CASCADE"),
        UniqueConstraint("run_item_id", "attempt_number", name="uq_experiment_run_attempt_number"),
        Index("ix_experiment_run_attempts_item_created", "run_item_id", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_item_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[ExperimentRunItemStatus] = mapped_column(SqlEnum(ExperimentRunItemStatus, name="experiment_attempt_status", native_enum=False, create_constraint=True), nullable=False)
    usage: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
