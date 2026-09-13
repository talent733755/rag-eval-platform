"""Candidate dataset browsing, review, publication, and archival endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from rag_eval_api.auth.rbac import (
    ProjectAccess,
    require_project_admin,
    require_project_editor,
    require_project_member,
)
from rag_eval_api.db import get_db_session
from rag_eval_api.models import (
    CandidateDataset,
    CandidateDatasetItem,
    CandidateDatasetStatus,
    CandidateDatasetVersion,
    CandidateReviewStatus,
)
from rag_eval_api.schemas.candidates import (
    CandidateDatasetResponse,
    CandidateDatasetVersionResponse,
    CandidateItemResponse,
    CandidateReviewRequest,
)
from rag_eval_api.services.audit import record_audit_event

router = APIRouter(prefix="/api/projects/{project_id}", tags=["candidate-datasets"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404, detail={"error": {"code": "not_found", "message": "Resource not found."}}
    )


async def _dataset(
    db_session: AsyncSession, access: ProjectAccess, dataset_id: UUID
) -> CandidateDataset:
    dataset = await db_session.scalar(
        select(CandidateDataset).where(
            CandidateDataset.id == dataset_id,
            CandidateDataset.organization_id == access.actor.organization_id,
            CandidateDataset.project_id == access.project.id,
        )
    )
    if dataset is None:
        raise _not_found()
    return dataset


async def _version(
    db_session: AsyncSession, access: ProjectAccess, dataset_id: UUID, version_id: UUID
) -> CandidateDatasetVersion:
    version = await db_session.scalar(
        select(CandidateDatasetVersion).where(
            CandidateDatasetVersion.id == version_id,
            CandidateDatasetVersion.dataset_id == dataset_id,
            CandidateDatasetVersion.organization_id == access.actor.organization_id,
            CandidateDatasetVersion.project_id == access.project.id,
        )
    )
    if version is None:
        raise _not_found()
    return version


@router.get("/candidate-datasets", response_model=list[CandidateDatasetResponse])
async def list_candidate_datasets(
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[CandidateDataset]:
    return list(
        (
            await db_session.scalars(
                select(CandidateDataset)
                .where(
                    CandidateDataset.organization_id == access.actor.organization_id,
                    CandidateDataset.project_id == access.project.id,
                )
                .order_by(CandidateDataset.updated_at.desc())
            )
        ).all()
    )


@router.get("/candidate-datasets/{dataset_id}", response_model=CandidateDatasetResponse)
async def get_candidate_dataset(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> CandidateDataset:
    return await _dataset(db_session, access, dataset_id)


@router.get(
    "/candidate-datasets/{dataset_id}/versions",
    response_model=list[CandidateDatasetVersionResponse],
)
async def list_candidate_dataset_versions(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[CandidateDatasetVersion]:
    await _dataset(db_session, access, dataset_id)
    return list(
        (
            await db_session.scalars(
                select(CandidateDatasetVersion)
                .where(
                    CandidateDatasetVersion.dataset_id == dataset_id,
                    CandidateDatasetVersion.organization_id == access.actor.organization_id,
                    CandidateDatasetVersion.project_id == access.project.id,
                )
                .order_by(CandidateDatasetVersion.version_number.desc())
            )
        ).all()
    )


@router.get(
    "/candidate-datasets/{dataset_id}/versions/{version_id}/items",
    response_model=list[CandidateItemResponse],
)
async def list_candidate_items(
    dataset_id: UUID,
    version_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[CandidateDatasetItem]:
    await _version(db_session, access, dataset_id, version_id)
    result = await db_session.scalars(
        select(CandidateDatasetItem)
        .options(selectinload(CandidateDatasetItem.evidence))
        .where(
            CandidateDatasetItem.dataset_id == dataset_id,
            CandidateDatasetItem.dataset_version_id == version_id,
            CandidateDatasetItem.organization_id == access.actor.organization_id,
            CandidateDatasetItem.project_id == access.project.id,
        )
        .order_by(CandidateDatasetItem.created_at, CandidateDatasetItem.id)
    )
    return list(result.all())


@router.post(
    "/candidate-datasets/{dataset_id}/versions/{version_id}/review",
    response_model=CandidateItemResponse,
)
async def review_candidate_item(
    dataset_id: UUID,
    version_id: UUID,
    payload: CandidateReviewRequest,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> CandidateDatasetItem:
    version = await _version(db_session, access, dataset_id, version_id)
    if version.status in {CandidateDatasetStatus.published, CandidateDatasetStatus.archived}:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "dataset_version_immutable",
                    "message": "Published or archived dataset versions cannot be reviewed.",
                }
            },
        )
    item = await db_session.scalar(
        select(CandidateDatasetItem)
        .options(selectinload(CandidateDatasetItem.evidence))
        .where(
            CandidateDatasetItem.id == payload.item_id,
            CandidateDatasetItem.dataset_id == dataset_id,
            CandidateDatasetItem.dataset_version_id == version_id,
            CandidateDatasetItem.organization_id == access.actor.organization_id,
            CandidateDatasetItem.project_id == access.project.id,
        )
    )
    if item is None:
        raise _not_found()
    item.review_status = CandidateReviewStatus(payload.review_status)
    if version.status is CandidateDatasetStatus.draft:
        version.status = CandidateDatasetStatus.review
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="candidate_item.reviewed",
        resource_type="candidate_dataset_item",
        resource_id=str(item.id),
        metadata={"review_status": payload.review_status, "comment": payload.comment},
    )
    await db_session.commit()
    return item


@router.post(
    "/candidate-datasets/{dataset_id}/versions/{version_id}/publish",
    response_model=CandidateDatasetVersionResponse,
)
async def publish_candidate_dataset_version(
    dataset_id: UUID,
    version_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> CandidateDatasetVersion:
    dataset = await _dataset(db_session, access, dataset_id)
    version = await _version(db_session, access, dataset_id, version_id)
    if version.status is CandidateDatasetStatus.published:
        return version
    pending = await db_session.scalar(
        select(func.count(CandidateDatasetItem.id)).where(
            CandidateDatasetItem.dataset_version_id == version.id,
            CandidateDatasetItem.review_status != CandidateReviewStatus.accepted,
        )
    )
    if pending:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "candidate_items_pending_review",
                    "message": "All candidate items must be accepted before publication.",
                }
            },
        )
    now = datetime.now(UTC)
    version.status = CandidateDatasetStatus.published
    version.published_at = now
    dataset.status = CandidateDatasetStatus.published
    dataset.published_at = now
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="candidate_dataset_version.published",
        resource_type="candidate_dataset_version",
        resource_id=str(version.id),
        metadata={"dataset_id": str(dataset.id), "item_count": version.item_count},
    )
    await db_session.commit()
    return version


@router.post(
    "/candidate-datasets/{dataset_id}/versions/{version_id}/archive",
    response_model=CandidateDatasetVersionResponse,
)
async def archive_candidate_dataset_version(
    dataset_id: UUID,
    version_id: UUID,
    access: ProjectAccess = Depends(require_project_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> CandidateDatasetVersion:
    version = await _version(db_session, access, dataset_id, version_id)
    version.status = CandidateDatasetStatus.archived
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="candidate_dataset_version.archived",
        resource_type="candidate_dataset_version",
        resource_id=str(version.id),
        metadata={"dataset_id": str(dataset_id)},
    )
    await db_session.commit()
    return version
