"""Candidate generation entrypoint with honest provider capability checks."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor
from rag_eval_api.db import get_db_session
from rag_eval_api.routes.documents import _scoped_version
from rag_eval_api.schemas.candidates import CandidateGenerationRequest

router = APIRouter(prefix="/api/projects/{project_id}", tags=["candidates"])


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message}},
    )


@router.post("/documents/{document_id}/generate-candidates", status_code=202)
async def generate_candidates(
    project_id: UUID,
    document_id: UUID,
    payload: CandidateGenerationRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Validate an explicit source version before creating generation work."""

    if not idempotency_key.strip() or len(idempotency_key.strip()) > 255:
        raise _error(422, "validation_error", "Idempotency-Key must be 1 to 255 characters.")
    version = await _scoped_version(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        document_id=document_id,
        version_id=payload.document_version_id,
    )
    if version.parse_status.value != "succeeded":
        raise _error(
            409, "document_version_not_parsed", "Document version has not parsed successfully."
        )
    settings = getattr(request.app.state, "settings", None)
    if settings is None or settings.provider_base_url is None:
        raise _error(
            503,
            "provider_not_configured",
            "No candidate generation provider is configured.",
        )
    raise _error(
        501,
        "candidate_generation_not_ready",
        "Candidate generation persistence is not available in this deployment.",
    )
