"""Transactional creation of candidate-generation snapshots and jobs."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rag_eval_api.candidates.protocol import CAPABILITY_VERSION
from rag_eval_api.models import (
    CandidateDataset,
    CandidateDatasetStatus,
    CandidateDatasetVersion,
    CandidateGenerationConfig,
    Document,
    DocumentChunk,
    DocumentParseStatus,
    DocumentVersion,
    IngestionJob,
    IngestionJobKind,
    IngestionJobStatus,
)
from rag_eval_api.schemas.candidates import CandidateGenerationRequest


def resolve_version_ids(payload: CandidateGenerationRequest) -> list[UUID]:
    """Primary ``document_version_id`` first, then any extra versions (deduped, stable order)."""

    ids = [payload.document_version_id]
    for extra in payload.document_version_ids or []:
        if extra not in ids:
            ids.append(extra)
    return ids


class CandidateGenerationError(ValueError):
    """A safe, stable candidate generation request error."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def create_generation_job(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    project_id: UUID,
    actor_id: UUID,
    document_id: UUID,
    idempotency_key: str,
    payload: CandidateGenerationRequest,
    provider_name: str,
    model_name: str,
) -> tuple[IngestionJob, CandidateDatasetVersion]:
    """Create one immutable generation snapshot and its durable job."""

    version_ids = resolve_version_ids(payload)
    versions = list(
        (
            await db_session.scalars(
                select(DocumentVersion).where(
                    DocumentVersion.id.in_(version_ids),
                    DocumentVersion.organization_id == organization_id,
                    DocumentVersion.project_id == project_id,
                )
            )
        ).all()
    )
    version_by_id = {item.id: item for item in versions}
    document = await db_session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == organization_id,
            Document.project_id == project_id,
        )
    )
    if document is None or any(vid not in version_by_id for vid in version_ids):
        raise CandidateGenerationError("not_found", "Resource not found.", status_code=404)
    primary = version_by_id[payload.document_version_id]
    if primary.document_id != document_id:
        raise CandidateGenerationError("not_found", "Resource not found.", status_code=404)
    if document.archived_at is not None or document.deleted_at is not None:
        raise CandidateGenerationError(
            "document_archived", "Archived documents cannot generate candidates."
        )
    for item in versions:
        if item.parse_status is not DocumentParseStatus.succeeded:
            raise CandidateGenerationError(
                "document_version_not_parsed", "Document version has not parsed successfully."
            )

    chunks = list(
        (
            await db_session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_version_id.in_(version_ids),
                    DocumentChunk.organization_id == organization_id,
                    DocumentChunk.project_id == project_id,
                )
                .order_by(
                    DocumentChunk.document_version_id, DocumentChunk.ordinal, DocumentChunk.id
                )
            )
        ).all()
    )
    # Order chunks by requested version order, then ordinal within each version.
    version_order = {vid: index for index, vid in enumerate(version_ids)}
    chunks.sort(key=lambda chunk: (version_order[chunk.document_version_id], chunk.ordinal, chunk.id))
    if not chunks:
        raise CandidateGenerationError(
            "document_has_no_chunks", "Document version has no parsed chunks."
        )

    chunk_hashes = [chunk.content_hash for chunk in chunks]
    fingerprint_payload = {
        "document_version_id": str(primary.id),
        "document_version_ids": [str(vid) for vid in version_ids],
        "dataset_name": payload.dataset_name,
        "capability_version": payload.capability_version,
        "prompt_version": payload.prompt_version,
        "seed": payload.seed,
        "randomness": payload.randomness,
        "chunk_content_hashes": chunk_hashes,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    existing = await db_session.scalar(
        select(IngestionJob).where(
            IngestionJob.organization_id == organization_id,
            IngestionJob.project_id == project_id,
            IngestionJob.job_kind == IngestionJobKind.generate_candidates,
            IngestionJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise CandidateGenerationError(
                "idempotency_conflict", "Idempotency-Key was reused with different input."
            )
        if existing.candidate_dataset_id is None:
            raise CandidateGenerationError(
                "generation_job_invalid", "Stored generation job is invalid.", status_code=500
            )
        existing_version = await db_session.scalar(
            select(CandidateDatasetVersion).where(
                CandidateDatasetVersion.id == existing.candidate_dataset_version_id,
                CandidateDatasetVersion.organization_id == organization_id,
                CandidateDatasetVersion.project_id == project_id,
            )
        )
        if existing_version is None:
            raise CandidateGenerationError(
                "generation_job_invalid",
                "Stored generation version is unavailable.",
                status_code=500,
            )
        return existing, existing_version

    dataset = await db_session.scalar(
        select(CandidateDataset).where(
            CandidateDataset.organization_id == organization_id,
            CandidateDataset.project_id == project_id,
            CandidateDataset.name == payload.dataset_name,
        )
    )
    if dataset is None:
        dataset = CandidateDataset(
            organization_id=organization_id,
            project_id=project_id,
            name=payload.dataset_name,
            status=CandidateDatasetStatus.draft,
        )
        db_session.add(dataset)
        await db_session.flush()
    elif dataset.status is CandidateDatasetStatus.archived:
        raise CandidateGenerationError(
            "dataset_archived", "Archived datasets cannot receive candidates."
        )

    latest_number = await db_session.scalar(
        select(func.max(CandidateDatasetVersion.version_number)).where(
            CandidateDatasetVersion.dataset_id == dataset.id,
            CandidateDatasetVersion.organization_id == organization_id,
            CandidateDatasetVersion.project_id == project_id,
        )
    )
    dataset_version = CandidateDatasetVersion(
        organization_id=organization_id,
        project_id=project_id,
        dataset_id=dataset.id,
        version_number=(latest_number or 0) + 1,
        status=CandidateDatasetStatus.draft,
        item_count=0,
        source_snapshot_hash=hashlib.sha256("".join(chunk_hashes).encode()).hexdigest(),
        created_by=actor_id,
    )
    db_session.add(dataset_version)
    await db_session.flush()
    config = CandidateGenerationConfig(
        organization_id=organization_id,
        project_id=project_id,
        dataset_id=dataset.id,
        capability_version=CAPABILITY_VERSION,
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=payload.prompt_version,
        parser_version=primary.parser_version,
        seed=payload.seed,
        randomness=payload.randomness,
        requested_version_ids=[str(vid) for vid in version_ids],
        chunk_content_hashes=chunk_hashes,
        environment={"app_env": "server", "source": "candidate-generation-v1"},
        request_id=idempotency_key,
        usage={},
    )
    db_session.add(config)
    await db_session.flush()
    job = IngestionJob(
        organization_id=organization_id,
        project_id=project_id,
        job_kind=IngestionJobKind.generate_candidates,
        status=IngestionJobStatus.queued,
        candidate_dataset_id=dataset.id,
        source_version_id=primary.id,
        generation_config_id=config.id,
        candidate_dataset_version_id=dataset_version.id,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        total_units=len(chunks),
    )
    db_session.add(job)
    await db_session.commit()
    return job, dataset_version
