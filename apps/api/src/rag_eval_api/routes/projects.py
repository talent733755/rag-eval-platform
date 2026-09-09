"""Project and project-member endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.context import RequestActor, get_current_actor
from rag_eval_api.auth.rbac import (
    ProjectAccess,
    require_organization_admin,
    require_project_admin,
    require_project_member,
)
from rag_eval_api.db import get_db_session
from rag_eval_api.models import Membership, MembershipRole, Project
from rag_eval_api.schemas.projects import (
    MemberInviteRequest,
    MemberInviteResponse,
    MemberRoleUpdate,
    MembershipResponse,
    ProjectCreate,
    ProjectResponse,
)
from rag_eval_api.services.audit import record_audit_event

router = APIRouter(prefix="/api/projects", tags=["projects"])


def not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": {"code": "not_found", "message": "Resource not found."}},
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    actor: RequestActor = Depends(get_current_actor),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[Project]:
    statement = (
        select(Project)
        .join(
            Membership,
            and_(
                Membership.project_id == Project.id,
                Membership.organization_id == Project.organization_id,
            ),
        )
        .where(
            Membership.user_id == actor.user_id,
            Membership.organization_id == actor.organization_id,
            Project.organization_id == actor.organization_id,
        )
    )
    return list((await db_session.execute(statement)).scalars().unique().all())


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    actor: RequestActor = Depends(require_organization_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> Project:
    project = Project(
        organization_id=actor.organization_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
    )
    db_session.add(project)
    try:
        await db_session.flush()
        db_session.add(
            Membership(
                organization_id=actor.organization_id,
                project_id=project.id,
                user_id=actor.user_id,
                role=MembershipRole.admin,
            )
        )
        record_audit_event(
            db_session,
            organization_id=actor.organization_id,
            project_id=project.id,
            actor_id=actor.user_id,
            action="project.created",
            resource_type="project",
            resource_id=str(project.id),
            metadata={"slug": project.slug},
        )
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "conflict", "message": "Project slug already exists."}},
        ) from exc
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(access: ProjectAccess = Depends(require_project_member)) -> Project:
    return access.project


@router.get("/{project_id}/members", response_model=list[MembershipResponse])
async def list_project_members(
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[Membership]:
    statement = select(Membership).where(
        Membership.organization_id == access.actor.organization_id,
        Membership.project_id == access.project.id,
    )
    return list((await db_session.execute(statement)).scalars().all())


@router.post(
    "/{project_id}/members",
    response_model=MemberInviteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def invite_project_member(
    payload: MemberInviteRequest,
    access: ProjectAccess = Depends(require_project_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> MemberInviteResponse:
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="project.member.invited",
        resource_type="project_member_invitation",
        resource_id="pending-invitation",
        metadata={"email": payload.email, "role": payload.role.value, "status": "pending"},
    )
    await db_session.commit()
    return MemberInviteResponse(
        project_id=access.project.id,
        email=payload.email,
        role=payload.role,
        status="pending",
    )


async def _load_target_membership(
    access: ProjectAccess,
    membership_id: UUID,
    db_session: AsyncSession,
) -> Membership:
    statement = select(Membership).where(
        and_(
            Membership.id == membership_id,
            Membership.organization_id == access.actor.organization_id,
            Membership.project_id == access.project.id,
        )
    )
    membership = (await db_session.execute(statement)).scalar_one_or_none()
    if membership is None:
        raise not_found()
    return membership


@router.patch(
    "/{project_id}/members/{membership_id}",
    response_model=MembershipResponse,
)
async def update_project_member(
    membership_id: UUID,
    payload: MemberRoleUpdate,
    access: ProjectAccess = Depends(require_project_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> Membership:
    membership = await _load_target_membership(access, membership_id, db_session)
    previous_role = membership.role
    membership.role = payload.role
    await db_session.flush()
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="project.member.role_changed",
        resource_type="membership",
        resource_id=str(membership.id),
        metadata={"from_role": previous_role.value, "to_role": payload.role.value},
    )
    await db_session.commit()
    return membership


@router.delete(
    "/{project_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_project_member(
    membership_id: UUID,
    access: ProjectAccess = Depends(require_project_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> Response:
    membership = await _load_target_membership(access, membership_id, db_session)
    await db_session.delete(membership)
    await db_session.flush()
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="project.member.removed",
        resource_type="membership",
        resource_id=str(membership.id),
        metadata={"user_id": str(membership.user_id), "role": membership.role.value},
    )
    await db_session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
