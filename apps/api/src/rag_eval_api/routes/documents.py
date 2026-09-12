"""Tenant-scoped document upload endpoints."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import PurePosixPath
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from rag_eval_api.auth.rbac import ProjectAccess, require_project_editor
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
from rag_eval_api.schemas.ingestion import (
    DocumentUploadDocument,
    DocumentUploadJob,
    DocumentUploadResponse,
    DocumentUploadVersion,
)
from rag_eval_api.services.audit import record_audit_event
from rag_eval_api.services.ingestion_jobs import ensure_idempotency
from rag_eval_api.storage.errors import (
    BlobChecksumMismatch,
    BlobSecurityError,
    BlobSizeExceeded,
    BlobStoreError,
)
from rag_eval_api.storage.protocol import BlobStore, StoredBlob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/documents", tags=["documents"])

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
