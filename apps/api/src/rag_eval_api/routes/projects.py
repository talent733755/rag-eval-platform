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
    recheck_project_admin_and_lock_memberships,
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
PROJECT_SLUG_CONFLICT_MARKERS = (
    "uq_projects_organization_id_slug",
    "projects.organization_id, projects.slug",
)


def not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": {"code": "not_found", "message": "Resource not found."}},
    )


def project_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": {"code": "conflict", "message": "Project conflicts with existing data."}},
    )


def is_project_slug_conflict(exc: IntegrityError) -> bool:
    """Recognize only the project organization/slug uniqueness violation."""

    message = str(exc.orig).lower()
    return any(marker in message for marker in PROJECT_SLUG_CONFLICT_MARKERS)


def final_admin_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": {
                "code": "conflict",
                "message": "A project must retain at least one administrator.",
            }
        },
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
    duplicate = await db_session.execute(
        select(Project.id).where(
            Project.organization_id == actor.organization_id,
            Project.slug == payload.slug,
        )
    )
    if duplicate.scalar_one_or_none() is not None:
        await db_session.rollback()
        raise project_conflict()
    db_session.add(project)
    try:
        await db_session.flush()
    except IntegrityError as exc:
        await db_session.rollback()
        if not is_project_slug_conflict(exc):
            raise
        raise project_conflict() from exc
    try:
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
    except Exception:
        await db_session.rollback()
        raise
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
    try:
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
    except Exception:
        await db_session.rollback()
        raise
    return MemberInviteResponse(
        project_id=access.project.id,
        email=payload.email,
        role=payload.role,
        status="pending",
    )


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
    membership, memberships = await recheck_project_admin_and_lock_memberships(
        access, db_session, membership_id
    )
    if (
        membership.role is MembershipRole.admin
        and payload.role is not MembershipRole.admin
        and sum(item.role is MembershipRole.admin for item in memberships) == 1
    ):
        await db_session.rollback()
        raise final_admin_conflict()
    previous_role = membership.role
    try:
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
    except Exception:
        await db_session.rollback()
        raise
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
    membership, memberships = await recheck_project_admin_and_lock_memberships(
        access, db_session, membership_id
    )
    if (
        membership.role is MembershipRole.admin
        and sum(item.role is MembershipRole.admin for item in memberships) == 1
    ):
        await db_session.rollback()
        raise final_admin_conflict()
    try:
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
    except Exception:
        await db_session.rollback()
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)
