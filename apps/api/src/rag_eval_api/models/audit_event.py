"""Append-only audit event model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, Index, String, Uuid, event, text
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
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_audit_events_project_organization_projects",
            ondelete="RESTRICT",
        ),
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
        server_default=text("CURRENT_TIMESTAMP"),
    )

    organization: Mapped[Organization] = relationship(
        back_populates="audit_events",
        overlaps="project,audit_events",
    )
    project: Mapped[Project | None] = relationship(
        back_populates="audit_events",
        overlaps="organization,audit_events",
    )

    def __repr__(self) -> str:
        return f"AuditEvent(id={self.id!r}, action={self.action!r}, actor_id={self.actor_id!r})"


def _validate_audit_event_tenant(target: AuditEvent) -> None:
    organization = target.organization
    project = target.project
    project_organization = project.organization if project is not None else None
    if organization is None or project is None:
        return
    if project_organization is not None:
        mismatched = project_organization.id != organization.id
    else:
        mismatched = (
            organization.id is not None
            and project.organization_id is not None
            and project.organization_id != organization.id
        )
    if mismatched:
        raise ValueError("organization and project must belong to the same tenant")


@event.listens_for(AuditEvent, "before_insert")
def _validate_audit_event_before_insert(mapper: object, connection: object, target: AuditEvent) -> None:
    del mapper, connection
    _validate_audit_event_tenant(target)


@event.listens_for(AuditEvent, "before_update")
def _validate_audit_event_before_update(mapper: object, connection: object, target: AuditEvent) -> None:
    del mapper, connection
    _validate_audit_event_tenant(target)


@event.listens_for(AuditEvent, "before_update")
def _reject_audit_event_update(mapper: object, connection: object, target: AuditEvent) -> None:
    del mapper, connection, target
    raise ValueError("AuditEvent records are append-only")


@event.listens_for(AuditEvent, "before_delete")
def _reject_audit_event_delete(mapper: object, connection: object, target: AuditEvent) -> None:
    del mapper, connection, target
    raise ValueError("AuditEvent records are append-only")
