"""Candidate generation entrypoint with honest provider capability checks."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor
from rag_eval_api.db import get_db_session
from rag_eval_api.schemas.candidates import (
    CandidateGenerationJobResponse,
    CandidateGenerationRequest,
)
from rag_eval_api.services.candidate_generation import (
    CandidateGenerationError,
    create_generation_job,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["candidates"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message}},
    )


@router.post(
    "/documents/{document_id}/generate-candidates",
    status_code=202,
    response_model=CandidateGenerationJobResponse,
)
async def generate_candidates(
    project_id: UUID,
    document_id: UUID,
    payload: CandidateGenerationRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> CandidateGenerationJobResponse:
    """Create a durable generation snapshot when a provider is configured."""

    if not idempotency_key.strip() or len(idempotency_key.strip()) > 255:
        raise _error(422, "validation_error", "Idempotency-Key must be 1 to 255 characters.")
    settings = getattr(request.app.state, "settings", None)
    if settings is None or settings.provider_base_url is None:
        raise _error(
            503,
            "provider_not_configured",
            "No candidate generation provider is configured.",
        )
    try:
        job, dataset_version = await create_generation_job(
            db_session,
            organization_id=access.actor.organization_id,
            project_id=project_id,
            actor_id=access.actor.user_id,
            document_id=document_id,
            idempotency_key=idempotency_key.strip(),
            payload=payload,
            provider_name="openai-compatible",
            model_name=getattr(settings, "provider_model_name", "configured-model"),
        )
    except CandidateGenerationError as exc:
        raise _error(exc.status_code, exc.code, exc.message) from exc
    return CandidateGenerationJobResponse(
        job_id=job.id,
        dataset_id=dataset_version.dataset_id,
        dataset_version_id=dataset_version.id,
        status=job.status.value,
    )
