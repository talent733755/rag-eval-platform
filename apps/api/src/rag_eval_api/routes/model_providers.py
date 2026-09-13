"""Project-scoped model provider configuration endpoints."""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import (
    ProjectAccess,
    require_project_admin,
    require_project_editor,
    require_project_member,
)
from rag_eval_api.candidates.errors import ProviderTransportError
from rag_eval_api.candidates.transport import ProviderTransport
from rag_eval_api.db import get_db_session
from rag_eval_api.models import ModelProviderConfig, ModelProviderTestStatus
from rag_eval_api.schemas.model_providers import (
    ModelProviderCreate,
    ModelProviderResponse,
    ModelProviderUpdate,
)
from rag_eval_api.services.audit import record_audit_event

router = APIRouter(prefix="/api/projects/{project_id}/model-providers", tags=["model-providers"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": {"code": code, "message": message}}
    )


async def _get_provider(
    provider_id: UUID, access: ProjectAccess, db_session: AsyncSession
) -> ModelProviderConfig:
    provider = await db_session.scalar(
        select(ModelProviderConfig).where(
            ModelProviderConfig.id == provider_id,
            ModelProviderConfig.organization_id == access.actor.organization_id,
            ModelProviderConfig.project_id == access.project.id,
        )
    )
    if provider is None:
        raise _error(404, "not_found", "Resource not found.")
    return provider


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
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="model_provider.created",
        resource_type="model_provider_config",
        resource_id=str(provider.id),
        metadata={"enabled": payload.enabled},
    )
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise _error(409, "model_provider_name_conflict", "Model provider name already exists in this project.") from exc
    return provider


@router.get("/{provider_id}", response_model=ModelProviderResponse)
async def get_model_provider(
    provider_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> ModelProviderConfig:
    return await _get_provider(provider_id, access, db_session)


@router.patch("/{provider_id}", response_model=ModelProviderResponse)
async def update_model_provider(
    provider_id: UUID,
    payload: ModelProviderUpdate,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> ModelProviderConfig:
    provider = await _get_provider(provider_id, access, db_session)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(provider, field, value)
    provider.last_test_status = ModelProviderTestStatus.never
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="model_provider.updated",
        resource_type="model_provider_config",
        resource_id=str(provider.id),
        metadata={"fields": sorted(changes)},
    )
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise _error(409, "model_provider_name_conflict", "Model provider name already exists in this project.") from exc
    return provider


@router.delete("/{provider_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_provider(
    provider_id: UUID,
    access: ProjectAccess = Depends(require_project_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> None:
    provider = await _get_provider(provider_id, access, db_session)
    resource_id = str(provider.id)
    await db_session.delete(provider)
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="model_provider.deleted",
        resource_type="model_provider_config",
        resource_id=resource_id,
        metadata={},
    )
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise _error(409, "model_provider_in_use", "Model provider cannot be deleted while referenced.") from exc


@router.post("/{provider_id}/test", response_model=ModelProviderResponse)
async def test_model_provider(
    provider_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> ModelProviderConfig:
    provider = await _get_provider(provider_id, access, db_session)
    token = os.getenv(provider.credential_ref)
    if token is None:
        provider.last_test_status = ModelProviderTestStatus.failed
        await db_session.commit()
        raise _error(503, "provider_credentials_unavailable", "Provider credential reference is not available.")
    settings = request.app.state.settings
    try:
        transport = ProviderTransport(
            provider.endpoint,
            api_key=token,
            app_env=settings.app_env,
            allowed_hosts=settings.provider_allowed_hosts,
            allowed_ports=settings.provider_allowed_ports,
            timeout_seconds=provider.timeout_seconds,
        )
        transport.post_json({
            "model": provider.model_name,
            "messages": [{"role": "user", "content": "连接测试"}],
            "max_tokens": 1,
        })
    except ProviderTransportError as exc:
        provider.last_test_status = ModelProviderTestStatus.failed
        await db_session.commit()
        raise _error(503 if exc.retryable else 502, exc.code, "Model provider connection test failed safely.") from exc
    except (TypeError, ValueError) as exc:
        provider.last_test_status = ModelProviderTestStatus.failed
        await db_session.commit()
        raise _error(422, "provider_configuration_invalid", "Model provider configuration is not allowed.") from exc
    provider.last_test_status = ModelProviderTestStatus.succeeded
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="model_provider.tested",
        resource_type="model_provider_config",
        resource_id=str(provider.id),
        metadata={"status": "succeeded"},
    )
    await db_session.commit()
    return provider
