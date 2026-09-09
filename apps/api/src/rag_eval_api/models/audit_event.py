"""Append-only audit event model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_eval_api.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, utc_now

if TYPE_CHECKING:
    from rag_eval_api.models.organization import Organization
    from rag_eval_api.models.project import Project


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """An immutable record of an administrative or project-scoped action.

    Application services should only insert these records. There are deliberately no
    update/delete helpers, and actor identity is retained as an external UUID.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_audit_events_project_id_created_at", "project_id", "created_at"),
        Index("ix_audit_events_created_at", "created_at"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )

    organization: Mapped[Organization] = relationship(back_populates="audit_events")
    project: Mapped[Project | None] = relationship(back_populates="audit_events")

    def __repr__(self) -> str:
        return f"AuditEvent(id={self.id!r}, action={self.action!r}, actor_id={self.actor_id!r})"
