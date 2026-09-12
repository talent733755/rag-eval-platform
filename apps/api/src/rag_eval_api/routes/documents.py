"""Tenant-scoped document upload endpoints."""

from __future__ import annotations

import hashlib
import json
import logging
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor, require_project_member
from rag_eval_api.config import DEFAULT_MAX_UPLOAD_BYTES, Settings
from rag_eval_api.db import get_db_session
from rag_eval_api.models import (
    Document,
    DocumentParseStatus,
    DocumentSourceType,
    DocumentVersion,
    IngestionJob,
    IngestionJobKind,
    IngestionJobStatus,
)
from rag_eval_api.models.base import utc_now
from rag_eval_api.schemas.ingestion import (
    DocumentJobResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadDocument,
    DocumentUploadJob,
    DocumentUploadResponse,
    DocumentUploadVersion,
    DocumentVersionListResponse,
    DocumentVersionResponse,
)
from rag_eval_api.services.audit import record_audit_event
from rag_eval_api.services.ingestion_jobs import IngestionJobState, ensure_idempotency
from rag_eval_api.storage.errors import (
    BlobChecksumMismatch,
    BlobSecurityError,
    BlobSizeExceeded,
    BlobStoreError,
)
from rag_eval_api.storage.protocol import BlobStore, StoredBlob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/documents", tags=["documents"])
job_router = APIRouter(prefix="/api/projects/{project_id}/ingestion-jobs", tags=["ingestion-jobs"])

_UPLOAD_FORMATS: dict[str, tuple[DocumentSourceType, str, frozenset[str]]] = {
    ".pdf": (DocumentSourceType.pdf, "application/pdf", frozenset({"application/pdf"})),
    ".docx": (
        DocumentSourceType.docx,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ),
    ".md": (
        DocumentSourceType.markdown,
        "text/markdown",
        frozenset({"text/markdown", "text/plain", "text/x-markdown"}),
    ),
    ".markdown": (
        DocumentSourceType.markdown,
        "text/markdown",
        frozenset({"text/markdown", "text/plain", "text/x-markdown"}),
    ),
    ".txt": (DocumentSourceType.txt, "text/plain", frozenset({"text/plain"})),
}
_READ_CHUNK_SIZE = 1024 * 1024
_MAX_PAGE_SIZE = 100
_RETRYABLE_PARSE_ERRORS = frozenset(
    {"parse_failed", "parse_timeout", "parser_sandbox_unavailable", "blob_store_error"}
)


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, str] | None = None,
) -> HTTPException:
    payload: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return HTTPException(status_code=status_code, detail={"error": payload})


def get_blob_store(request: Request) -> BlobStore:
    """Resolve the opaque blob boundary from application state.

    The route never receives or returns a local filesystem root. Production
    startup is responsible for attaching a concrete BlobStore implementation;
    tests and alternate deployments can inject any protocol-compatible backend.
    """

    blob_store = getattr(request.app.state, "blob_store", None)
    if blob_store is None:
        raise _error(503, "blob_store_error", "Blob storage is not configured.")
    return cast(BlobStore, blob_store)


def _settings(request: Request) -> Settings | None:
    configured = getattr(request.app.state, "settings", None)
    return configured if isinstance(configured, Settings) else None


def _max_upload_bytes(request: Request) -> int:
    configured = _settings(request)
    return configured.max_upload_bytes if configured is not None else DEFAULT_MAX_UPLOAD_BYTES


def _safe_filename(
    filename: str | None,
) -> tuple[str, str, DocumentSourceType, str, frozenset[str]]:
    display_name = PurePosixPath((filename or "").replace("\\", "/")).name
    suffix = PurePosixPath(display_name).suffix.lower()
    format_info = _UPLOAD_FORMATS.get(suffix)
    if not display_name or display_name in {".", ".."} or "\x00" in display_name:
        raise _error(415, "unsupported_type", "File name or extension is not supported.")
    if format_info is None:
        raise _error(415, "unsupported_type", "File extension is not supported.")
    source_type, detected_mime, accepted_mimes = format_info
    if len(display_name) > 255:
        raise _error(422, "validation_error", "File name is too long.")
    return display_name, suffix, source_type, detected_mime, accepted_mimes


def _validate_signature(suffix: str, prefix: bytes) -> None:
    if suffix == ".pdf" and not prefix.startswith(b"%PDF-"):
        raise _error(415, "unsupported_type", "PDF signature does not match the extension.")
    if suffix == ".docx" and not prefix.startswith(b"PK"):
        raise _error(415, "unsupported_type", "DOCX signature does not match the extension.")
    if suffix in {".md", ".markdown", ".txt"} and b"\x00" in prefix:
        raise _error(415, "unsupported_type", "Text input contains binary data.")


async def _inspect_upload(upload: UploadFile, *, max_bytes: int) -> tuple[int, str, bytes]:
    """Bounded streaming inspection that does not materialize the upload."""

    digest = hashlib.sha256()
    prefix = bytearray()
    byte_size = 0
    await upload.seek(0)
    while True:
        chunk = await upload.read(min(_READ_CHUNK_SIZE, max_bytes + 1 - byte_size))
        if not chunk:
            break
        byte_size += len(chunk)
        if byte_size > max_bytes:
            raise _error(413, "size_exceeded", "Uploaded file exceeds the configured size limit.")
        digest.update(chunk)
        if len(prefix) < 16:
            prefix.extend(chunk[: 16 - len(prefix)])
    await upload.seek(0)
    if byte_size == 0:
        raise _error(422, "validation_error", "Uploaded file must not be empty.")
    return byte_size, digest.hexdigest(), bytes(prefix)


def _request_fingerprint(
    *, display_name: str, source_type: DocumentSourceType, sha256: str, byte_size: int
) -> str:
    canonical = json.dumps(
        {
            "byte_size": byte_size,
            "display_name": display_name,
            "sha256": sha256,
            "source_type": source_type.value,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _find_job(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    idempotency_key: str,
) -> IngestionJob | None:
    return cast(
        IngestionJob | None,
        await db_session.scalar(
            select(IngestionJob).where(
                IngestionJob.organization_id == organization_id,
                IngestionJob.project_id == project_id,
                IngestionJob.job_kind == IngestionJobKind.parse,
                IngestionJob.idempotency_key == idempotency_key,
            )
        ),
    )


async def _find_duplicate(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    sha256: str,
    byte_size: int,
) -> tuple[Document, DocumentVersion] | None:
    result = await db_session.execute(
        select(Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(
            Document.organization_id == organization_id,
            Document.project_id == project_id,
            DocumentVersion.organization_id == organization_id,
            DocumentVersion.project_id == project_id,
            DocumentVersion.sha256 == sha256,
            DocumentVersion.byte_size == byte_size,
        )
    )
    row = result.first()
    if row is None:
        return None
    document, version = row
    return document, version


async def _load_job_response(db_session: AsyncSession, job: IngestionJob) -> DocumentUploadResponse:
    result = await db_session.execute(
        select(Document, DocumentVersion)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(
            Document.organization_id == job.organization_id,
            Document.project_id == job.project_id,
            DocumentVersion.organization_id == job.organization_id,
            DocumentVersion.project_id == job.project_id,
            DocumentVersion.id == job.document_version_id,
        )
    )
    row = result.first()
    if row is None:
        raise _error(500, "internal_server_error", "Stored upload records are incomplete.")
    document, version = row
    return DocumentUploadResponse(
        document=DocumentUploadDocument.model_validate(document),
        document_version=DocumentUploadVersion.model_validate(version),
        ingestion_job=DocumentUploadJob.model_validate(job),
    )


async def _delete_blob_quietly(blob_store: BlobStore, storage_key: str) -> None:
    try:
        await run_in_threadpool(blob_store.delete, storage_key)
    except Exception:
        logger.warning(
            "document upload cleanup failed",
            extra={"event": "document.upload.cleanup_failed", "storage_key_present": True},
        )


def _duplicate_error(document: Document, version: DocumentVersion) -> HTTPException:
    return _error(
        409,
        "duplicate_document",
        "The same content already exists in this project.",
        details={"document_id": str(document.id), "document_version_id": str(version.id)},
    )


def _cursor_encode(updated_at: datetime, resource_id: UUID) -> str:
    payload = json.dumps(
        {"updated_at": updated_at.isoformat(), "id": str(resource_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _cursor_decode(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        updated_at = datetime.fromisoformat(payload["updated_at"])
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return updated_at, UUID(payload["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise _error(422, "validation_error", "Cursor is invalid or expired.") from exc


def _version_response(version: DocumentVersion) -> DocumentVersionResponse:
    return DocumentVersionResponse.model_validate(version)


def _document_response(
    document: Document, latest_version: DocumentVersion | None
) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        organization_id=document.organization_id,
        project_id=document.project_id,
        display_name=document.display_name,
        source_type=document.source_type.value,
        latest_version_id=document.latest_version_id,
        archived_at=document.archived_at,
        deleted_at=document.deleted_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
        latest_version=_version_response(latest_version) if latest_version is not None else None,
    )


def _job_response(job: IngestionJob) -> DocumentJobResponse:
    return DocumentJobResponse(
        id=job.id,
        organization_id=job.organization_id,
        project_id=job.project_id,
        job_kind=job.job_kind.value,
        status=job.status.value,
        document_version_id=job.document_version_id,
        candidate_dataset_id=job.candidate_dataset_id,
        idempotency_key=job.idempotency_key,
        attempt_count=job.attempt_count,
        completed_units=job.completed_units,
        total_units=job.total_units,
        cancel_requested_at=job.cancel_requested_at,
        last_error_code=job.last_error_code,
    )


async def _scoped_document(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
) -> tuple[Document, DocumentVersion | None]:
    result = await db_session.execute(
        select(Document, DocumentVersion)
        .outerjoin(
            DocumentVersion,
            and_(
                DocumentVersion.id == Document.latest_version_id,
                DocumentVersion.organization_id == organization_id,
                DocumentVersion.project_id == project_id,
            ),
        )
        .where(
            Document.id == document_id,
            Document.organization_id == organization_id,
            Document.project_id == project_id,
        )
    )
    row = result.first()
    if row is None:
        raise _error(404, "not_found", "Resource not found.")
    document, version = row
    return document, version


async def _scoped_version(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> DocumentVersion:
    version = await db_session.scalar(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Document.id == document_id,
            Document.organization_id == organization_id,
            Document.project_id == project_id,
            DocumentVersion.id == version_id,
            DocumentVersion.organization_id == organization_id,
            DocumentVersion.project_id == project_id,
        )
    )
    if version is None:
        raise _error(404, "not_found", "Resource not found.")
    return version


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    project_id: UUID,
    page_size: int = Query(default=50, ge=1, le=_MAX_PAGE_SIZE),
    cursor: str | None = None,
    q: str | None = None,
    source_type: str | None = None,
    parse_status: str | None = None,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> DocumentListResponse:
    """List active documents with stable, opaque cursor pagination."""

    base_filters = [
        Document.organization_id == access.actor.organization_id,
        Document.project_id == project_id,
        Document.archived_at.is_(None),
        Document.deleted_at.is_(None),
    ]
    filters = list(base_filters)
    if q:
        filters.append(Document.display_name.ilike(f"%{q.strip()}%"))
    if source_type is not None:
        if source_type not in {item.value for item in DocumentSourceType}:
            raise _error(422, "validation_error", "source_type is not supported.")
        filters.append(Document.source_type == source_type)
    if parse_status is not None:
        if parse_status not in {item.value for item in DocumentParseStatus}:
            raise _error(422, "validation_error", "parse_status is not supported.")
        filters.append(DocumentVersion.parse_status == parse_status)
    count_filters = list(filters)
    if cursor is not None:
        cursor_time, cursor_id = _cursor_decode(cursor)
        filters.append(
            or_(
                Document.updated_at < cursor_time,
                and_(Document.updated_at == cursor_time, Document.id < cursor_id),
            )
        )

    statement = (
        select(Document, DocumentVersion)
        .outerjoin(
            DocumentVersion,
            and_(
                DocumentVersion.id == Document.latest_version_id,
                DocumentVersion.organization_id == access.actor.organization_id,
                DocumentVersion.project_id == project_id,
            ),
        )
        .where(*filters)
        .order_by(Document.updated_at.desc(), Document.id.desc())
        .limit(page_size + 1)
    )
    rows = list((await db_session.execute(statement)).all())
    has_next = len(rows) > page_size
    rows = rows[:page_size]
    items = [_document_response(document, version) for document, version in rows]
    next_cursor = _cursor_encode(rows[-1][0].updated_at, rows[-1][0].id) if has_next else None
    count_statement = (
        select(func.count())
        .select_from(Document)
        .outerjoin(
            DocumentVersion,
            and_(
                DocumentVersion.id == Document.latest_version_id,
                DocumentVersion.organization_id == access.actor.organization_id,
                DocumentVersion.project_id == project_id,
            ),
        )
        .where(*count_filters)
    )
    total = int((await db_session.scalar(count_statement)) or 0)
    return DocumentListResponse(
        items=items,
        next_cursor=next_cursor,
        summary={"total": total},
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    project_id: UUID,
    document_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> DocumentResponse:
    document, latest_version = await _scoped_document(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        document_id=document_id,
    )
    return _document_response(document, latest_version)


@router.get("/{document_id}/versions", response_model=DocumentVersionListResponse)
async def list_document_versions(
    project_id: UUID,
    document_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> DocumentVersionListResponse:
    await _scoped_document(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        document_id=document_id,
    )
    versions = list(
        (
            await db_session.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.organization_id == access.actor.organization_id,
                    DocumentVersion.project_id == project_id,
                    DocumentVersion.document_id == document_id,
                )
                .order_by(DocumentVersion.version_number.desc())
            )
        ).all()
    )
    return DocumentVersionListResponse(
        items=[_version_response(version) for version in versions],
        next_cursor=None,
    )


@router.get("/{document_id}/versions/{version_id}", response_model=DocumentVersionResponse)
async def get_document_version(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> DocumentVersionResponse:
    version = await _scoped_version(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
    )
    return _version_response(version)


@router.post(
    "/{document_id}/versions/{version_id}/retry-parse",
    response_model=DocumentJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_document_parse(
    project_id: UUID,
    document_id: UUID,
    version_id: UUID,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> DocumentJobResponse:
    """Queue a fresh parse job while retaining the previous job history."""

    idempotency_key = idempotency_key.strip()
    if not idempotency_key or len(idempotency_key) > 255:
        raise _error(422, "validation_error", "Idempotency-Key must be 1 to 255 characters.")
    version = await _scoped_version(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        document_id=document_id,
        version_id=version_id,
    )
    fingerprint = hashlib.sha256(str(version_id).encode("ascii")).hexdigest()
    existing = await _find_job(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        try:
            ensure_idempotency(
                (project_id, IngestionJobKind.parse.value, idempotency_key),
                fingerprint,
                existing.request_fingerprint,
            )
        except ValueError as exc:
            raise _error(
                409,
                "idempotency_conflict",
                "Idempotency-Key was already used with a different request.",
            ) from exc
        return _job_response(existing)

    previous = await db_session.scalar(
        select(IngestionJob)
        .where(
            IngestionJob.organization_id == access.actor.organization_id,
            IngestionJob.project_id == project_id,
            IngestionJob.document_version_id == version_id,
            IngestionJob.job_kind == IngestionJobKind.parse,
        )
        .order_by(IngestionJob.created_at.desc())
    )
    if previous is None or previous.status.value not in {"failed", "blocked"}:
        raise _error(409, "conflict", "Document version is not eligible for parse retry.")
    if (
        previous.status.value == "failed"
        and previous.last_error_code not in _RETRYABLE_PARSE_ERRORS
    ):
        raise _error(409, "conflict", "Document version is not eligible for parse retry.")
    try:
        IngestionJobState.retry_target(
            previous.status.value,
            retryable=previous.status.value == "blocked"
            or previous.last_error_code in _RETRYABLE_PARSE_ERRORS,
        )
        version.parse_status = DocumentParseStatus.queued
        job = IngestionJob(
            organization_id=access.actor.organization_id,
            project_id=project_id,
            job_kind=IngestionJobKind.parse,
            status=IngestionJobStatus.queued,
            document_version_id=version_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        db_session.add(job)
        record_audit_event(
            db_session,
            organization_id=access.actor.organization_id,
            project_id=project_id,
            actor_id=access.actor.user_id,
            action="document.parse.retry",
            resource_type="document_version",
            resource_id=str(version_id),
            metadata={
                "request_id": str(uuid4()),
                "idempotency_key_sha256": hashlib.sha256(
                    idempotency_key.encode("utf-8")
                ).hexdigest(),
            },
        )
        await db_session.commit()
        return _job_response(job)
    except IntegrityError as exc:
        await db_session.rollback()
        existing = await _find_job(
            db_session,
            organization_id=access.actor.organization_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return _job_response(existing)
        raise _error(409, "conflict", "Parse retry conflicts with existing data.") from exc


async def _scoped_job(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    job_id: UUID,
) -> IngestionJob:
    job = await db_session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.organization_id == organization_id,
            IngestionJob.project_id == project_id,
        )
    )
    if job is None:
        raise _error(404, "not_found", "Resource not found.")
    return job


@job_router.get("/{job_id}", response_model=DocumentJobResponse)
async def get_ingestion_job(
    project_id: UUID,
    job_id: UUID,
    access: ProjectAccess = Depends(require_project_member),
    db_session: AsyncSession = Depends(get_db_session),
) -> DocumentJobResponse:
    job = await _scoped_job(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        job_id=job_id,
    )
    return _job_response(job)


@job_router.post("/{job_id}/cancel", response_model=DocumentJobResponse)
async def cancel_ingestion_job(
    project_id: UUID,
    job_id: UUID,
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
) -> DocumentJobResponse:
    job = await _scoped_job(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        job_id=job_id,
    )
    try:
        IngestionJobState.cancel_target(job.status.value)
    except ValueError as exc:
        raise _error(
            409, "conflict", "Ingestion job cannot be cancelled in its current state."
        ) from exc
    job.status = IngestionJobStatus.cancelled
    job.cancel_requested_at = utc_now()
    if job.document_version_id is not None:
        version = await db_session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == job.document_version_id,
                DocumentVersion.organization_id == access.actor.organization_id,
                DocumentVersion.project_id == project_id,
            )
        )
        if version is not None and version.parse_status in {
            DocumentParseStatus.queued,
            DocumentParseStatus.processing,
        }:
            version.parse_status = DocumentParseStatus.cancelled
    record_audit_event(
        db_session,
        organization_id=access.actor.organization_id,
        project_id=project_id,
        actor_id=access.actor.user_id,
        action="ingestion.cancelled",
        resource_type="ingestion_job",
        resource_id=str(job.id),
        metadata={"request_id": str(uuid4())},
    )
    await db_session.commit()
    return _job_response(job)


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    project_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
    access: ProjectAccess = Depends(require_project_editor),
    db_session: AsyncSession = Depends(get_db_session),
    blob_store: BlobStore = Depends(get_blob_store),
) -> DocumentUploadResponse:
    """Store one new logical document and enqueue its parse job."""

    idempotency_key = idempotency_key.strip()
    if not idempotency_key or len(idempotency_key) > 255:
        raise _error(422, "validation_error", "Idempotency-Key must be 1 to 255 characters.")

    display_name, suffix, source_type, detected_mime, accepted_mimes = _safe_filename(file.filename)
    declared_mime = (file.content_type or "").split(";", 1)[0].strip().lower()
    if declared_mime and declared_mime not in accepted_mimes:
        raise _error(415, "unsupported_type", "Declared MIME does not match the extension.")

    byte_size, sha256, prefix = await _inspect_upload(file, max_bytes=_max_upload_bytes(request))
    _validate_signature(suffix, prefix)
    fingerprint = _request_fingerprint(
        display_name=display_name,
        source_type=source_type,
        sha256=sha256,
        byte_size=byte_size,
    )
    organization_id = access.actor.organization_id

    existing_job = await _find_job(
        db_session,
        organization_id=organization_id,
        project_id=project_id,
        idempotency_key=idempotency_key,
    )
    if existing_job is not None:
        try:
            ensure_idempotency(
                (project_id, IngestionJobKind.parse.value, idempotency_key),
                fingerprint,
                existing_job.request_fingerprint,
            )
        except ValueError as exc:
            raise _error(
                409,
                "idempotency_conflict",
                "Idempotency-Key was already used with a different request.",
            ) from exc
        return await _load_job_response(db_session, existing_job)

    duplicate = await _find_duplicate(
        db_session,
        organization_id=organization_id,
        project_id=project_id,
        sha256=sha256,
        byte_size=byte_size,
    )
    if duplicate is not None:
        raise _duplicate_error(*duplicate)

    stored: StoredBlob | None = None
    try:
        stored = await run_in_threadpool(
            blob_store.put,
            file.file,
            expected_sha256=sha256,
            max_bytes=_max_upload_bytes(request),
        )
        if stored.sha256 != sha256 or stored.byte_size != byte_size:
            raise _error(422, "checksum_mismatch", "Stored upload metadata does not match input.")

        # Repeat both checks after the blob commit to handle concurrent uploads.
        existing_job = await _find_job(
            db_session,
            organization_id=organization_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        if existing_job is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
            try:
                ensure_idempotency(
                    (project_id, IngestionJobKind.parse.value, idempotency_key),
                    fingerprint,
                    existing_job.request_fingerprint,
                )
            except ValueError as exc:
                raise _error(
                    409,
                    "idempotency_conflict",
                    "Idempotency-Key was already used with a different request.",
                ) from exc
            return await _load_job_response(db_session, existing_job)

        duplicate = await _find_duplicate(
            db_session,
            organization_id=organization_id,
            project_id=project_id,
            sha256=sha256,
            byte_size=byte_size,
        )
        if duplicate is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
            raise _duplicate_error(*duplicate)

        document = Document(
            organization_id=organization_id,
            project_id=project_id,
            display_name=display_name,
            source_type=source_type,
        )
        version = DocumentVersion(
            organization_id=organization_id,
            project_id=project_id,
            document=document,
            version_number=1,
            sha256=stored.sha256,
            byte_size=stored.byte_size,
            detected_mime=detected_mime,
            storage_key=stored.storage_key,
            parse_status=DocumentParseStatus.queued,
        )
        db_session.add_all([document, version])
        await db_session.flush()
        document.latest_version_id = version.id
        job = IngestionJob(
            organization_id=organization_id,
            project_id=project_id,
            job_kind=IngestionJobKind.parse,
            status=IngestionJobStatus.queued,
            document_version_id=version.id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        db_session.add(job)
        record_audit_event(
            db_session,
            organization_id=organization_id,
            project_id=project_id,
            actor_id=access.actor.user_id,
            action="document.uploaded",
            resource_type="document",
            resource_id=str(document.id),
            metadata={
                "request_id": str(getattr(request.state, "request_id", uuid4())),
                "sha256": sha256,
                "byte_size": byte_size,
                "source_type": source_type.value,
                "idempotency_key_sha256": hashlib.sha256(
                    idempotency_key.encode("utf-8")
                ).hexdigest(),
            },
        )
        await db_session.commit()
        return DocumentUploadResponse(
            document=DocumentUploadDocument.model_validate(document),
            document_version=DocumentUploadVersion.model_validate(version),
            ingestion_job=DocumentUploadJob.model_validate(job),
        )
    except HTTPException:
        await db_session.rollback()
        if stored is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
        raise
    except BlobSizeExceeded as exc:
        await db_session.rollback()
        if stored is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
        raise _error(
            413, "size_exceeded", "Uploaded file exceeds the configured size limit."
        ) from exc
    except BlobChecksumMismatch as exc:
        await db_session.rollback()
        if stored is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
        raise _error(
            422, "checksum_mismatch", "Uploaded file checksum could not be verified."
        ) from exc
    except BlobSecurityError as exc:
        await db_session.rollback()
        if stored is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
        raise _error(
            503, "blob_security_error", "Blob storage rejected the upload safely."
        ) from exc
    except BlobStoreError as exc:
        await db_session.rollback()
        if stored is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
        raise _error(503, "blob_store_error", "Blob storage could not accept the upload.") from exc
    except IntegrityError as exc:
        await db_session.rollback()
        if stored is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
        existing_job = await _find_job(
            db_session,
            organization_id=organization_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        if existing_job is not None:
            try:
                ensure_idempotency(
                    (project_id, IngestionJobKind.parse.value, idempotency_key),
                    fingerprint,
                    existing_job.request_fingerprint,
                )
            except ValueError as conflict:
                raise _error(
                    409,
                    "idempotency_conflict",
                    "Idempotency-Key was already used with a different request.",
                ) from conflict
            return await _load_job_response(db_session, existing_job)
        duplicate = await _find_duplicate(
            db_session,
            organization_id=organization_id,
            project_id=project_id,
            sha256=sha256,
            byte_size=byte_size,
        )
        if duplicate is not None:
            raise _duplicate_error(*duplicate) from exc
        raise _error(409, "conflict", "Upload conflicts with existing project data.") from exc
    except Exception:
        await db_session.rollback()
        if stored is not None:
            await _delete_blob_quietly(blob_store, stored.storage_key)
        raise
