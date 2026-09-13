"""Append-only tenant-scoped Trace and failure history."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from rag_eval_api.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class PersistedTrace(UUIDPrimaryKeyMixin, Base):
    """A validated trace snapshot linked to one experiment run item."""

    __tablename__ = "traces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["experiment_id", "organization_id", "project_id"],
            ["experiments.id", "experiments.organization_id", "experiments.project_id"],
            name="fk_traces_experiment_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "organization_id", "project_id"],
            ["experiment_runs.id", "experiment_runs.organization_id", "experiment_runs.project_id"],
            name="fk_traces_run_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_item_id", "organization_id", "project_id"],
            [
                "experiment_run_items.id",
                "experiment_run_items.organization_id",
                "experiment_run_items.project_id",
            ],
            name="fk_traces_item_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_item_id", "trace_id", name="uq_traces_run_item_trace"),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_traces_tenant"),
        Index("ix_traces_project_created", "organization_id", "project_id", "created_at"),
        Index("ix_traces_run_item", "run_item_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    experiment_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_item_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    trace_version: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stages: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default="CURRENT_TIMESTAMP"
    )


class FailureCase(UUIDPrimaryKeyMixin, Base):
    """One primary safe diagnosis for one failed adapter attempt."""

    __tablename__ = "failure_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["experiment_id", "organization_id", "project_id"],
            ["experiments.id", "experiments.organization_id", "experiments.project_id"],
            name="fk_failure_cases_experiment_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "organization_id", "project_id"],
            ["experiment_runs.id", "experiment_runs.organization_id", "experiment_runs.project_id"],
            name="fk_failure_cases_run_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_item_id", "organization_id", "project_id"],
            [
                "experiment_run_items.id",
                "experiment_run_items.organization_id",
                "experiment_run_items.project_id",
            ],
            name="fk_failure_cases_item_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_item_id", "attempt_number", name="uq_failure_cases_item_attempt"),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_failure_cases_tenant"),
        Index("ix_failure_cases_project_created", "organization_id", "project_id", "created_at"),
        Index("ix_failure_cases_run_code", "run_id", "code"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    experiment_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    run_item_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    safe_message: Mapped[str] = mapped_column(String(500), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default="CURRENT_TIMESTAMP"
    )


def _reject_mutation(mapper: object, connection: object, target: object) -> None:
    del mapper, connection, target
    raise ValueError("Trace and failure records are append-only")


for _model in (PersistedTrace, FailureCase):
    event.listen(_model, "before_update", _reject_mutation)
    event.listen(_model, "before_delete", _reject_mutation)
