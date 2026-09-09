"""Project and organization membership authorization dependencies.

The foundation schema has project memberships but no separate organization
membership table. Until that table exists, an actor with an ``admin``
membership in any project belonging to an organization is treated as an
organization administrator. Every query still scopes both the actor and the
organization explicitly so this compatibility policy cannot cross tenants.

Administrative mutation routes recheck and lock membership rows in the same
transaction. PostgreSQL honors ``FOR UPDATE``; SQLite ignores row locks, so
SQLite tests verify state and atomicity but cannot model production lock
contention.
"""

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
    *,
    for_update: bool = False,
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
    if for_update:
        statement = statement.with_for_update()
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
    project_id: UUID,
    actor: RequestActor = Depends(get_current_actor),
    db_session: AsyncSession = Depends(get_db_session),
) -> ProjectAccess:
    """Require project administrator access."""

    access = await _load_project_access(project_id, actor, db_session, for_update=True)
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
    ).limit(1).with_for_update()
    if (await db_session.execute(statement)).scalar_one_or_none() is None:
        raise permission_denied()
    return actor


async def recheck_project_admin_and_lock_memberships(
    access: ProjectAccess,
    db_session: AsyncSession,
    membership_id: UUID,
) -> tuple[Membership, list[Membership]]:
    """Recheck the actor and lock project memberships before an admin mutation."""

    statement = (
        select(Membership)
        .where(
            Membership.organization_id == access.actor.organization_id,
            Membership.project_id == access.project.id,
        )
        .with_for_update()
    )
    memberships = list((await db_session.execute(statement)).scalars().all())
    actor_membership = next(
        (membership for membership in memberships if membership.user_id == access.actor.user_id),
        None,
    )
    if actor_membership is None or actor_membership.role is not MembershipRole.admin:
        raise permission_denied()
    target = next((membership for membership in memberships if membership.id == membership_id), None)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Resource not found."}},
        )
    return target, memberships
