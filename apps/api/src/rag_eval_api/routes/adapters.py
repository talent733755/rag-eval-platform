"""Project-scoped adapter configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor, require_project_member
from rag_eval_api.db import get_db_session
from rag_eval_api.models import AdapterConfig, AdapterKind, AdapterTestStatus
from rag_eval_api.schemas.adapters import AdapterConfigCreate, AdapterConfigResponse
from rag_eval_api.services.audit import record_audit_event

router = APIRouter(prefix="/api/projects/{project_id}/adapters", tags=["adapters"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"error": {"code": code, "message": message}}
    )


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
    if payload.kind == "http" and not payload.endpoint:
        raise _error(422, "validation_error", "HTTP adapters require an endpoint.")
    if payload.kind == "python" and payload.endpoint:
        raise _error(422, "validation_error", "Python adapters do not accept an endpoint.")
    adapter = AdapterConfig(
        organization_id=access.actor.organization_id,
        project_id=access.project.id,
        name=payload.name,
        kind=AdapterKind(payload.kind),
        endpoint=payload.endpoint,
        credential_ref=payload.credential_ref,
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
