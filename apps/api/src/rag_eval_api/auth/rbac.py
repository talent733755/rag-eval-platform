"""Project and organization membership authorization dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.context import RequestActor, get_current_actor
from rag_eval_api.db import get_db_session
from rag_eval_api.models import Membership, MembershipRole, Project

PERMISSION_DENIED_DETAIL = {
    "error": {
        "code": "permission_denied",
        "message": "You do not have permission to perform this action.",
    }
}


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    """A project and the actor's membership, loaded as one authorization unit."""

    project: Project
    membership: Membership
    actor: RequestActor


def permission_denied() -> HTTPException:
    """Return the single public permission-denied response."""

    return HTTPException(status_code=403, detail=PERMISSION_DENIED_DETAIL)


async def _load_project_access(
    project_id: UUID,
    actor: RequestActor,
    db_session: AsyncSession,
) -> ProjectAccess:
    statement = (
        select(Project, Membership)
        .join(
            Membership,
            and_(
                Membership.project_id == Project.id,
                Membership.organization_id == Project.organization_id,
            ),
        )
        .where(
            Project.id == project_id,
            Project.organization_id == actor.organization_id,
            Membership.organization_id == actor.organization_id,
            Membership.user_id == actor.user_id,
        )
    )
    row = (await db_session.execute(statement)).first()
    if row is None:
        raise permission_denied()
    project, membership = row
    return ProjectAccess(project=project, membership=membership, actor=actor)


async def require_project_member(
    project_id: UUID,
    actor: RequestActor = Depends(get_current_actor),
    db_session: AsyncSession = Depends(get_db_session),
) -> ProjectAccess:
    """Require membership in the actor's organization and the requested project."""

    return await _load_project_access(project_id, actor, db_session)


async def require_project_editor(
    access: ProjectAccess = Depends(require_project_member),
) -> ProjectAccess:
    """Require project editor or administrator access."""

    if access.membership.role not in {MembershipRole.editor, MembershipRole.admin}:
        raise permission_denied()
    return access


async def require_project_admin(
    access: ProjectAccess = Depends(require_project_member),
) -> ProjectAccess:
    """Require project administrator access."""

    if access.membership.role is not MembershipRole.admin:
        raise permission_denied()
    return access


async def require_organization_admin(
    actor: RequestActor = Depends(get_current_actor),
    db_session: AsyncSession = Depends(get_db_session),
) -> RequestActor:
    """Require an administrator membership in the actor's organization."""

    statement = select(Membership.id).where(
        Membership.organization_id == actor.organization_id,
        Membership.user_id == actor.user_id,
        Membership.role == MembershipRole.admin,
    )
    if (await db_session.execute(statement)).scalar_one_or_none() is None:
        raise permission_denied()
    return actor
