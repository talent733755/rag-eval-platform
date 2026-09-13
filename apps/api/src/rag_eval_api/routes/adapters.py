"""Project-scoped adapter configuration endpoints."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.adapters import Adapter, AdapterRequest, HttpAdapter, load_python_adapter
from rag_eval_api.adapters.errors import AdapterError
from rag_eval_api.auth.rbac import (
    ProjectAccess,
    require_project_admin,
    require_project_editor,
    require_project_member,
)
from rag_eval_api.db import get_db_session
from rag_eval_api.models import AdapterConfig, AdapterKind, AdapterTestStatus
from rag_eval_api.schemas.adapters import (
    AdapterConfigCreate,
    AdapterConfigResponse,
    AdapterConfigUpdate,
)
from rag_eval_api.services.audit import record_audit_event

router = APIRouter(prefix="/api/projects/{project_id}/adapters", tags=["adapters"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": {"code": code, "message": message}}
    )


async def _get_adapter(
    adapter_id: UUID, access: ProjectAccess, db_session: AsyncSession
) -> AdapterConfig:
    adapter = await db_session.scalar(
        select(AdapterConfig).where(
            AdapterConfig.id == adapter_id,
            AdapterConfig.organization_id == access.actor.organization_id,
            AdapterConfig.project_id == access.project.id,
        )
    )
    if adapter is None:
        raise _error(404, "not_found", "Resource not found.")
    return adapter


def _validate_adapter_shape(
    kind: AdapterKind, endpoint: str | None, entrypoint_ref: str | None
) -> None:
    if kind is AdapterKind.http and not endpoint:
        raise _error(422, "validation_error", "HTTP adapters require an endpoint.")
    if kind is AdapterKind.python and endpoint:
        raise _error(422, "validation_error", "Python adapters do not accept an endpoint.")
    if kind is AdapterKind.python and not entrypoint_ref:
        raise _error(422, "validation_error", "Python adapters require an entry point reference.")
    if kind is AdapterKind.http and entrypoint_ref:
        raise _error(422, "validation_error", "HTTP adapters do not accept an entry point reference.")


@router.get("", response_model=list[AdapterConfigResponse])
async def list_adapters(
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> list[AdapterConfig]:
    return list(
        (
            await db_session.scalars(
                select(AdapterConfig)
                .where(
                    AdapterConfig.organization_id == access.actor.organization_id,
                    AdapterConfig.project_id == access.project.id,
                )
                .order_by(AdapterConfig.name)
            )
        ).all()
    )


@router.post("", response_model=AdapterConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_adapter(
    payload: AdapterConfigCreate,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> AdapterConfig:
    _validate_adapter_shape(AdapterKind(payload.kind), payload.endpoint, payload.entrypoint_ref)
    adapter = AdapterConfig(
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        name=payload.name,
        kind=AdapterKind(payload.kind),
        endpoint=payload.endpoint,
        credential_ref=payload.credential_ref,
        entrypoint_ref=payload.entrypoint_ref,
        adapter_version=payload.adapter_version,
        trace_level=payload.trace_level,
        timeout_seconds=payload.timeout_seconds,
        retry_count=payload.retry_count,
        enabled=payload.enabled,
        last_test_status=AdapterTestStatus.never,
    )
    db_session.add(adapter)
    try:
        await db_session.flush()
    except IntegrityError as exc:
        await db_session.rollback()
        raise _error(
            409, "adapter_name_conflict", "Adapter name already exists in this project."
        ) from exc
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="adapter.created",
        resource_type="adapter_config",
        resource_id=str(adapter.id),
        metadata={"kind": payload.kind, "enabled": payload.enabled},
    )
    await db_session.commit()
    return adapter


@router.get("/{adapter_id}", response_model=AdapterConfigResponse)
async def get_adapter(
    adapter_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> AdapterConfig:
    return await _get_adapter(adapter_id, access, db_session)


@router.patch("/{adapter_id}", response_model=AdapterConfigResponse)
async def update_adapter(
    adapter_id: UUID,
    payload: AdapterConfigUpdate,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> AdapterConfig:
    adapter = await _get_adapter(adapter_id, access, db_session)
    changes = payload.model_dump(exclude_unset=True)
    effective_kind = AdapterKind(changes.get("kind", adapter.kind))
    effective_endpoint = changes.get("endpoint", adapter.endpoint)
    effective_entrypoint_ref = changes.get("entrypoint_ref", adapter.entrypoint_ref)
    _validate_adapter_shape(effective_kind, effective_endpoint, effective_entrypoint_ref)
    for field, value in changes.items():
        setattr(adapter, field, AdapterKind(value) if field == "kind" else value)
    adapter.last_test_status = AdapterTestStatus.never
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="adapter.updated",
        resource_type="adapter_config",
        resource_id=str(adapter.id),
        metadata={"fields": sorted(changes)},
    )
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise _error(409, "adapter_name_conflict", "Adapter name already exists in this project.") from exc
    return adapter


@router.delete("/{adapter_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
async def delete_adapter(
    adapter_id: UUID,
    access: ProjectAccess = Depends(require_project_admin),
    db_session: AsyncSession = Depends(get_db_session),
) -> None:
    adapter = await _get_adapter(adapter_id, access, db_session)
    resource_id = str(adapter.id)
    await db_session.delete(adapter)
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="adapter.deleted",
        resource_type="adapter_config",
        resource_id=resource_id,
        metadata={},
    )
    try:
        await db_session.commit()
    except IntegrityError as exc:
        await db_session.rollback()
        raise _error(409, "adapter_in_use", "Adapter cannot be deleted while it is referenced.") from exc


@router.post("/{adapter_id}/test", response_model=AdapterConfigResponse)
async def test_adapter(
    adapter_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> AdapterConfig:
    adapter = await _get_adapter(adapter_id, access, db_session)
    token = os.getenv(adapter.credential_ref) if adapter.credential_ref else None
    if adapter.credential_ref and token is None:
        adapter.last_test_status = AdapterTestStatus.failed
        await db_session.commit()
        raise _error(503, "adapter_credentials_unavailable", "Adapter credential reference is not available.")

    try:
        settings = request.app.state.settings
        if adapter.kind is AdapterKind.http and adapter.endpoint:
            implementation: Adapter = HttpAdapter(
                adapter.endpoint,
                bearer_token=token,
                adapter_version=adapter.adapter_version,
                trace_level=adapter.trace_level,
                app_env=settings.app_env,
                allowed_hosts=settings.provider_allowed_hosts,
                allowed_ports=settings.provider_allowed_ports,
                timeout_seconds=adapter.timeout_seconds,
            )
        elif adapter.kind is AdapterKind.python:
            implementation = load_python_adapter(
                adapter.entrypoint_ref,
                adapter_version=adapter.adapter_version,
                trace_level=adapter.trace_level,
                timeout_seconds=adapter.timeout_seconds,
            )
        else:
            raise TypeError("adapter configuration is incomplete")
        implementation.run(
            AdapterRequest(
                request_id=str(uuid4()),
                question="连接测试",
                metadata={"purpose": "connection_test"},
                timeout_seconds=adapter.timeout_seconds,
            )
        )
    except AdapterError as exc:
        adapter.last_test_status = AdapterTestStatus.failed
        await db_session.commit()
        raise _error(503 if exc.retryable else 502, exc.code, "Adapter connection test failed safely.") from exc
    except (TypeError, ValueError) as exc:
        adapter.last_test_status = AdapterTestStatus.failed
        await db_session.commit()
        raise _error(422, "adapter_configuration_invalid", "Adapter configuration is not allowed.") from exc

    adapter.last_test_status = AdapterTestStatus.succeeded
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        actor_id=access.actor.user_id,
        action="adapter.tested",
        resource_type="adapter_config",
        resource_id=str(adapter.id),
        metadata={"status": "succeeded"},
    )
    await db_session.commit()
    return adapter
