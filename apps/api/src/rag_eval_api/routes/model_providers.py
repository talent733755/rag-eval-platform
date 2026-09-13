"""Project-scoped model provider configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor, require_project_member
from rag_eval_api.db import get_db_session
from rag_eval_api.models import ModelProviderConfig, ModelProviderTestStatus
from rag_eval_api.schemas.model_providers import ModelProviderCreate, ModelProviderResponse

router = APIRouter(prefix="/api/projects/{project_id}/model-providers", tags=["model-providers"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": {"code": code, "message": message}}
    )


@router.get("", response_model=list[ModelProviderResponse])
async def list_model_providers(
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[ModelProviderConfig]:
    return list(
        (
            await db_session.scalars(
                select(ModelProviderConfig)
                .where(
                    ModelProviderConfig.organization_id == access.actor.organization_id,
                    ModelProviderConfig.project_id == access.project.id,
                )
                .order_by(ModelProviderConfig.name)
            )
        ).all()
    )


@router.post("", response_model=ModelProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_model_provider(
    payload: ModelProviderCreate,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> ModelProviderConfig:
    provider = ModelProviderConfig(
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        name=payload.name,
        endpoint=payload.endpoint,
        credential_ref=payload.credential_ref,
        model_name=payload.model_name,
        timeout_seconds=payload.timeout_seconds,
        enabled=payload.enabled,
        last_test_status=ModelProviderTestStatus.never,
    )
    db_session.add(provider)
    await db_session.commit()
    return provider
