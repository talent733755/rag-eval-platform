"""Tenant-scoped, secret-free RAG adapter configuration models."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from rag_eval_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AdapterKind(str, Enum):
    http = "http"
    python = "python"


class AdapterTestStatus(str, Enum):
    never = "never"
    succeeded = "succeeded"
    failed = "failed"


class AdapterConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A configured adapter without any credential material."""

    __tablename__ = "adapter_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", "project_id", "name", name="uq_adapter_configs_name"),
        CheckConstraint("length(trim(name)) > 0", name="adapter_name_nonempty"),
        CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 300", name="adapter_timeout_range"
        ),
        CheckConstraint("retry_count >= 0 AND retry_count <= 5", name="adapter_retry_range"),
        Index("ix_adapter_configs_project_enabled", "organization_id", "project_id", "enabled"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[AdapterKind] = mapped_column(
        SqlEnum(AdapterKind, name="adapter_kind", native_enum=False, create_constraint=True),
        nullable=False,
    )
    endpoint: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    adapter_version: Mapped[str] = mapped_column(String(100), nullable=False)
    trace_level: Mapped[str] = mapped_column(String(20), nullable=False, default="minimal")
    timeout_seconds: Mapped[float] = mapped_column(nullable=False, default=30)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_test_status: Mapped[AdapterTestStatus] = mapped_column(
        SqlEnum(
            AdapterTestStatus,
            name="adapter_test_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
        default=AdapterTestStatus.never,
    )
