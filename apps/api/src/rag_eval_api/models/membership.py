"""Project membership and role model."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, ForeignKeyConstraint, UniqueConstraint, Uuid, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rag_eval_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from rag_eval_api.models.organization import Organization
    from rag_eval_api.models.project import Project


class MembershipRole(str, Enum):
    """Roles supported by the foundation permission model."""

    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """External user identity membership scoped to one organization project."""

    __tablename__ = "memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            name="fk_memberships_project_organization_projects",
            ondelete="CASCADE",
        ),
        UniqueConstraint("project_id", "user_id", name="uq_memberships_project_id_user_id"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    role: Mapped[MembershipRole] = mapped_column(
        SqlEnum(
            MembershipRole,
            name="membership_role",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )

    organization: Mapped[Organization] = relationship(
        back_populates="memberships",
        overlaps="project,memberships",
    )
    project: Mapped[Project] = relationship(
        back_populates="memberships",
        overlaps="organization,memberships",
    )

    def __repr__(self) -> str:
        return (
            f"Membership(id={self.id!r}, project_id={self.project_id!r}, user_id={self.user_id!r})"
        )


def _validate_membership_tenant(target: Membership) -> None:
    organization = target.organization
    project = target.project
    if organization is None or project is None:
        return
    project_organization = project.organization
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


@event.listens_for(Membership, "before_insert")
def _validate_membership_before_insert(
    mapper: object, connection: object, target: Membership
) -> None:
    del mapper, connection
    _validate_membership_tenant(target)


@event.listens_for(Membership, "before_update")
def _validate_membership_before_update(
    mapper: object, connection: object, target: Membership
) -> None:
    del mapper, connection
    _validate_membership_tenant(target)
