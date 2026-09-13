"""Tenant-scoped model provider configuration without secret material."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from rag_eval_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModelProviderTestStatus(str, Enum):
    never = "never"
    succeeded = "succeeded"
    failed = "failed"


class ModelProviderConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A model endpoint reference; API keys are injected outside the database."""

    __tablename__ = "model_provider_configs"
    __table_args__ = (
        UniqueConstraint("organization_id", "project_id", "name", name="uq_model_providers_name"),
        UniqueConstraint(
            "id", "organization_id", "project_id", name="uq_model_provider_configs_tenant"
        ),
        CheckConstraint("length(trim(name)) > 0", name="model_provider_name_nonempty"),
        CheckConstraint(
            "timeout_seconds > 0 AND timeout_seconds <= 300", name="model_provider_timeout_range"
        ),
        Index("ix_model_providers_project_enabled", "organization_id", "project_id", "enabled"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(2048), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(nullable=False, default=30, server_default="30")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_test_status: Mapped[ModelProviderTestStatus] = mapped_column(
        SqlEnum(ModelProviderTestStatus, name="model_provider_test_status", native_enum=False),
        nullable=False,
        default=ModelProviderTestStatus.never,
        server_default="never",
    )
