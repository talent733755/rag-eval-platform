"""Durable parse worker for queued document ingestion jobs."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_eval_api.models import (
    Document,
    DocumentChunk,
    DocumentParseStatus,
    DocumentVersion,
    IngestionAttemptFinalStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobKind,
    IngestionJobLease,
    IngestionJobStatus,
)
from rag_eval_api.parsers.errors import ParserError
from rag_eval_api.parsers.models import ParseResult
from rag_eval_api.parsers.registry import ParserRegistry
from rag_eval_api.services.audit import record_audit_event
from rag_eval_api.services.blob_reconciliation import (
    BlobReconciliationResult,
    reconcile_orphaned_blobs,
)
from rag_eval_api.services.ingestion_jobs import IngestionJobState
from rag_eval_api.storage.errors import BlobStoreError
from rag_eval_api.storage.protocol import BlobStore

LOGGER = logging.getLogger(__name__)
SYSTEM_ACTOR_ID = UUID(int=0)


@dataclass(frozen=True, slots=True)
class _Claim:
    job_id: UUID
    organization_id: UUID
    project_id: UUID
    document_version_id: UUID
    display_name: str
    detected_mime: str
    storage_key: str
    sha256: str
    byte_size: int
    lease_id: UUID
    attempt_number: int
    fencing_token: int
    worker_id: str
    started_at: datetime


@dataclass(frozen=True, slots=True)
class _Failure:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class WorkerBatchResult:
    """Counters for one bounded worker batch."""

    processed: int
    succeeded: int
    failed: int
    cancelled: int
    lease_lost: int = 0

    @property
    def claimed(self) -> int:
        """Compatibility name for callers interested in claimed jobs."""

        return self.processed


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    """Counters and timing for one maintenance pass."""

    recovered_jobs: int
    reconciliation: BlobReconciliationResult | None
    failed_count: int
    duration_ms: float

    @property
    def orphan_blobs_deleted(self) -> int:
        """Number of orphaned objects deleted during this pass."""

        return self.reconciliation.deleted if self.reconciliation is not None else 0


class WorkerProcessingError(Exception):
    """A bounded, classified failure raised while processing one job."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class _HeartbeatFailure(WorkerProcessingError):
    """Internal signal used to stop parsing after a lease heartbeat fails."""


class IngestionWorker:
    """Claim and execute bounded parse jobs using PostgreSQL as source of truth."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        blob_store: BlobStore,
        parser_registry: ParserRegistry | Any | None = None,
        parser_limits: Any | None = None,
        worker_id: str,
        lease_ttl: timedelta = timedelta(seconds=60),
        batch_size: int = 1,
        heartbeat_interval: timedelta | None = None,
        orphan_blob_grace_period: timedelta = timedelta(hours=1),
    ) -> None:
        if not worker_id.strip() or len(worker_id) > 255:
            raise ValueError("worker_id must be 1 to 255 characters")
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        effective_heartbeat_interval = heartbeat_interval or lease_ttl / 3
        if effective_heartbeat_interval <= timedelta(0):
            raise ValueError("heartbeat_interval must be positive")
        if effective_heartbeat_interval >= lease_ttl:
            raise ValueError("heartbeat_interval must be less than lease_ttl")
        if orphan_blob_grace_period < timedelta(0):
            raise ValueError("orphan_blob_grace_period must not be negative")
        self.session_factory = session_factory
        self.blob_store = blob_store
        self.parser_registry = parser_registry or ParserRegistry()
        self.parser_limits = parser_limits
        self.worker_id = worker_id
        self.lease_ttl = lease_ttl
        self.batch_size = batch_size
        self.heartbeat_interval = effective_heartbeat_interval
        self.orphan_blob_grace_period = orphan_blob_grace_period
        self._shutdown_requested = False
        self._shutdown_event = asyncio.Event()
        self._active_parse_task: asyncio.Task[Any] | None = None

    def request_shutdown(self) -> None:
        """Stop claiming jobs and cancel the currently running parse task."""

        self._shutdown_requested = True
        self._shutdown_event.set()
        if self._active_parse_task is not None and not self._active_parse_task.done():
            self._active_parse_task.cancel()

    async def run_once(self) -> bool:
        """Process one queued parse job; return false when no job is claimable."""

        return await self._process_one() is not None

    async def process_batch(self, limit: int) -> WorkerBatchResult:
        """Process at most ``limit`` claimable jobs and return terminal counters."""

        if limit < 1:
            raise ValueError("limit must be positive")
        outcomes: list[str] = []
        for _ in range(limit):
            outcome = await self._process_one()
            if outcome is None:
                break
            outcomes.append(outcome)
        return WorkerBatchResult(
            processed=len(outcomes),
            succeeded=outcomes.count(IngestionAttemptFinalStatus.succeeded.value),
            failed=outcomes.count(IngestionAttemptFinalStatus.failed.value),
            cancelled=outcomes.count(IngestionAttemptFinalStatus.cancelled.value),
            lease_lost=outcomes.count("lease_lost"),
        )

    async def run_maintenance(self) -> MaintenanceResult:
        """Recover expired work and reconcile old unreferenced blobs."""

        started = time.perf_counter()
        recovered_jobs = 0
        reconciliation: BlobReconciliationResult | None = None
        failed_count = 0
        try:
            recovered_jobs = await self.recover_expired_jobs()
        except Exception:
            failed_count += 1
            LOGGER.exception(
                "worker maintenance recovery failed",
                extra={"event": "worker.maintenance.recovery_failed"},
            )
        try:
            async with self.session_factory() as session:
                reconciliation = await reconcile_orphaned_blobs(
                    session,
                    self.blob_store,
                    grace_period=self.orphan_blob_grace_period,
                )
        except Exception:
            failed_count += 1
            LOGGER.exception(
                "worker maintenance blob reconciliation failed",
                extra={"event": "worker.maintenance.reconciliation_failed"},
            )
        if reconciliation is not None:
            failed_count += reconciliation.delete_failed
        result = MaintenanceResult(
            recovered_jobs=recovered_jobs,
            reconciliation=reconciliation,
            failed_count=failed_count,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        LOGGER.info(
            "worker maintenance completed",
            extra={
                "event": "worker.maintenance.completed",
                "recovered_jobs": result.recovered_jobs,
                "orphan_blobs_scanned": (
                    result.reconciliation.scanned if result.reconciliation is not None else 0
                ),
                "orphan_blobs_deleted": result.orphan_blobs_deleted,
                "failed_count": result.failed_count,
                "duration_ms": result.duration_ms,
            },
        )
        return result

    async def recover_expired_jobs(self, *, now: datetime | None = None) -> int:
        """Requeue processing jobs whose worker lease expired before finalization."""

        current_time = now or datetime.now(UTC)
        recovered = 0
        async with self.session_factory() as session:
            async with session.begin():
                leases = list(
                    (
                        await session.scalars(
                            select(IngestionJobLease)
                            .where(IngestionJobLease.lease_expires_at <= current_time)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                for lease in leases:
                    job = await session.scalar(
                        select(IngestionJob)
                        .where(
                            IngestionJob.id == lease.job_id,
                            IngestionJob.organization_id == lease.organization_id,
                            IngestionJob.project_id == lease.project_id,
                        )
                        .with_for_update()
                    )
                    if job is None or job.status is not IngestionJobStatus.processing:
                        continue
                    IngestionJobState.recover_target(job.status.value)
                    job.status = IngestionJobStatus.queued
                    if job.document_version_id is not None:
                        version = await session.scalar(
                            select(DocumentVersion).where(
                                DocumentVersion.id == job.document_version_id,
                                DocumentVersion.organization_id == job.organization_id,
                                DocumentVersion.project_id == job.project_id,
                            )
                        )
                        if (
                            version is not None
                            and version.parse_status is DocumentParseStatus.processing
                        ):
                            version.parse_status = DocumentParseStatus.queued
                    record_audit_event(
                        session,
                        organization_id=job.organization_id,
                        project_id=job.project_id,
                        actor_id=SYSTEM_ACTOR_ID,
                        action="ingestion.lease_expired",
                        resource_type="ingestion_job",
                        resource_id=str(job.id),
                        metadata={
                            "worker_id": lease.worker_id,
                            "attempt_number": lease.attempt_number,
                            "fencing_token": lease.fencing_token,
                        },
                    )
                    recovered += 1
        return recovered

    async def _claim_next(self) -> _Claim | None:
        if self._shutdown_requested:
            return None
        async with self.session_factory() as session:
            async with session.begin():
                statement = (
                    select(IngestionJob)
                    .where(
                        IngestionJob.job_kind == IngestionJobKind.parse,
                        IngestionJob.status == IngestionJobStatus.queued,
                    )
                    .order_by(IngestionJob.created_at, IngestionJob.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                job = (await session.execute(statement)).scalar_one_or_none()
                if job is None or job.document_version_id is None:
                    return None
                now = datetime.now(UTC)
                lease = await session.scalar(
                    select(IngestionJobLease)
                    .where(IngestionJobLease.job_id == job.id)
                    .with_for_update()
                )
                if lease is not None and lease.lease_expires_at > now:
                    return None
                version = await session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.id == job.document_version_id,
                        DocumentVersion.organization_id == job.organization_id,
                        DocumentVersion.project_id == job.project_id,
                    )
                )
                if version is None:
                    raise WorkerProcessingError(
                        "blob_not_found",
                        "Document version metadata is unavailable.",
                    )
                document = await session.scalar(
                    select(Document).where(
                        Document.id == version.document_id,
                        Document.organization_id == job.organization_id,
                        Document.project_id == job.project_id,
                    )
                )
                if document is None:
                    raise WorkerProcessingError(
                        "blob_not_found",
                        "Document version metadata is unavailable.",
                    )
                attempt_number = job.attempt_count + 1
                fencing_token = (lease.fencing_token + 1) if lease is not None else 1
                if lease is None:
                    lease = IngestionJobLease(
                        organization_id=job.organization_id,
                        project_id=job.project_id,
                        job_id=job.id,
                        attempt_number=attempt_number,
                        worker_id=self.worker_id,
                        lease_expires_at=now + self.lease_ttl,
                        heartbeat_at=now,
                        fencing_token=fencing_token,
                    )
                    session.add(lease)
                else:
                    lease.attempt_number = attempt_number
                    lease.worker_id = self.worker_id
                    lease.lease_expires_at = now + self.lease_ttl
                    lease.heartbeat_at = now
                    lease.fencing_token = fencing_token
                await session.flush()
                IngestionJobState.transition(job.status.value, IngestionJobStatus.processing.value)
                job.status = IngestionJobStatus.processing
                job.attempt_count = attempt_number
                job.completed_units = 0
                job.total_units = 0
                job.last_error_code = None
                job.last_error_message = None
                return _Claim(
                    job_id=job.id,
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    document_version_id=version.id,
                    display_name=document.display_name,
                    detected_mime=version.detected_mime,
                    storage_key=version.storage_key,
                    sha256=version.sha256,
                    byte_size=version.byte_size,
                    lease_id=lease.id,
                    attempt_number=attempt_number,
                    fencing_token=fencing_token,
                    worker_id=self.worker_id,
                    started_at=now,
                )

    async def _process_one(self) -> str | None:
        claim = await self._claim_next()
        if claim is None:
            return None
        failure: _Failure | None = None
        result: ParseResult | None = None
        try:
            result = await self._parse_with_heartbeat(claim)
        except Exception as exc:
            failure = self._classify_failure(exc)
        final_status = await self._finalize(claim, result=result, failure=failure)
        if final_status is not None:
            return final_status.value
        return "lease_lost" if failure is not None and failure.code == "lease_lost" else "discarded"

    async def _parse_with_heartbeat(self, claim: _Claim) -> ParseResult:
        """Run parsing beside a lease task so stale work cannot finalize."""

        parse_task = asyncio.create_task(self._parse(claim))
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(claim))
        self._active_parse_task = parse_task
        try:
            done, _ = await asyncio.wait(
                {parse_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                await heartbeat_task
            return await parse_task
        finally:
            self._active_parse_task = None
            for task in (parse_task, heartbeat_task):
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def _heartbeat_loop(self, claim: _Claim) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval.total_seconds())
            if not await self.heartbeat(claim.job_id, claim.lease_id, claim.fencing_token):
                if await self._is_cancel_requested(claim.job_id):
                    raise _HeartbeatFailure("cancelled", "Document parsing was cancelled.")
                LOGGER.warning(
                    "worker heartbeat lost lease",
                    extra={
                        "event": "worker.heartbeat_failed",
                        "job_id": str(claim.job_id),
                        "lease_id": str(claim.lease_id),
                        "fencing_token": claim.fencing_token,
                    },
                )
                raise _HeartbeatFailure(
                    "lease_lost",
                    "Worker lease could not be renewed.",
                    retryable=True,
                )

    async def heartbeat(self, job_id: UUID, lease_id: UUID, fencing_token: int) -> bool:
        """Renew a lease only when its job, lease row, and fence are current."""

        now = datetime.now(UTC)
        async with self.session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(IngestionJobLease)
                    .where(
                        IngestionJobLease.id == lease_id,
                        IngestionJobLease.job_id == job_id,
                        IngestionJobLease.fencing_token == fencing_token,
                        IngestionJobLease.lease_expires_at > now,
                    )
                    .values(
                        heartbeat_at=now,
                        lease_expires_at=now + self.lease_ttl,
                    )
                )
                if result.rowcount != 1:
                    LOGGER.warning(
                        "worker heartbeat rejected",
                        extra={
                            "event": "worker.heartbeat_rejected",
                            "job_id": str(job_id),
                            "lease_id": str(lease_id),
                            "fencing_token": fencing_token,
                        },
                    )
                    return False
                job = await session.scalar(select(IngestionJob).where(IngestionJob.id == job_id))
                if job is None or job.status is not IngestionJobStatus.processing:
                    return False
                return job.cancel_requested_at is None

    async def _is_cancel_requested(self, job_id: UUID) -> bool:
        async with self.session_factory() as session:
            job = await session.scalar(select(IngestionJob).where(IngestionJob.id == job_id))
            return job is not None and (
                job.cancel_requested_at is not None or job.status is IngestionJobStatus.cancelled
            )

    async def _parse(self, claim: _Claim) -> ParseResult:
        def parse_blob() -> ParseResult:
            with self.blob_store.open(claim.storage_key) as source:
                result = self.parser_registry.parse(
                    source,
                    filename=claim.display_name,
                    declared_mime=claim.detected_mime,
                    limits=self.parser_limits,
                )
            if result.content_hash != claim.sha256 or result.byte_size != claim.byte_size:
                raise WorkerProcessingError(
                    "checksum_mismatch",
                    "Parsed bytes do not match the stored document version.",
                )
            return result

        return await asyncio.to_thread(parse_blob)

    @staticmethod
    def _classify_failure(exc: Exception) -> _Failure:
        if isinstance(exc, WorkerProcessingError):
            return _Failure(exc.code, str(exc)[:200], exc.retryable)
        if isinstance(exc, ParserError):
            return _Failure(exc.code, str(exc)[:200], exc.retryable)
        if isinstance(exc, BlobStoreError):
            return _Failure(exc.code, str(exc)[:200], False)
        LOGGER.exception("worker parse failed unexpectedly")
        return _Failure("parse_failed", "Document parsing failed safely.", False)

    async def _finalize(
        self,
        claim: _Claim,
        *,
        result: ParseResult | None,
        failure: _Failure | None,
    ) -> IngestionAttemptFinalStatus | None:
        async with self.session_factory() as session:
            async with session.begin():
                job = await session.scalar(
                    select(IngestionJob)
                    .where(
                        IngestionJob.id == claim.job_id,
                        IngestionJob.organization_id == claim.organization_id,
                        IngestionJob.project_id == claim.project_id,
                    )
                    .with_for_update()
                )
                lease = await session.scalar(
                    select(IngestionJobLease)
                    .where(
                        IngestionJobLease.job_id == claim.job_id,
                        IngestionJobLease.organization_id == claim.organization_id,
                        IngestionJobLease.project_id == claim.project_id,
                    )
                    .with_for_update()
                )
                if job is None or lease is None or not self._lease_is_current(lease, claim):
                    LOGGER.warning(
                        "worker result discarded after lease loss",
                        extra={"event": "worker.lease_lost", "job_id": str(claim.job_id)},
                    )
                    return None
                now = datetime.now(UTC)
                version = await session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.id == claim.document_version_id,
                        DocumentVersion.organization_id == claim.organization_id,
                        DocumentVersion.project_id == claim.project_id,
                    )
                )
                if version is None:
                    failure = _Failure("blob_not_found", "Document version is unavailable.", False)
                cancelled = job.status is IngestionJobStatus.cancelled or job.cancel_requested_at
                if cancelled:
                    final_status = IngestionAttemptFinalStatus.cancelled
                    if version is not None:
                        version.parse_status = DocumentParseStatus.cancelled
                    error = _Failure("cancelled", "Document parsing was cancelled.", False)
                    job.last_error_code = error.code
                    job.last_error_message = error.message
                    job.status = IngestionJobStatus.cancelled
                elif failure is not None:
                    final_status = IngestionAttemptFinalStatus.failed
                    if version is not None:
                        version.parse_status = DocumentParseStatus.failed
                    job.status = IngestionJobStatus.failed
                    job.last_error_code = failure.code
                    job.last_error_message = failure.message
                    error = failure
                else:
                    assert result is not None
                    final_status = IngestionAttemptFinalStatus.succeeded
                    if version is not None:
                        version.parse_status = DocumentParseStatus.succeeded
                        version.parser_version = result.parser_version
                        version.parsed_character_count = sum(
                            chunk.character_count for chunk in result.chunks
                        )
                        version.page_count = result.page_count
                        for chunk in result.chunks:
                            location = dict(chunk.source_location)
                            page = location.get("page")
                            paragraph = location.get("paragraph")
                            session.add(
                                DocumentChunk(
                                    organization_id=claim.organization_id,
                                    project_id=claim.project_id,
                                    document_version_id=claim.document_version_id,
                                    ordinal=chunk.ordinal,
                                    heading=chunk.heading,
                                    content=chunk.content,
                                    content_hash=chunk.content_hash,
                                    page_number=page if isinstance(page, int) else None,
                                    paragraph_index=(
                                        paragraph if isinstance(paragraph, int) else None
                                    ),
                                    source_location=location,
                                    character_count=chunk.character_count,
                                    token_count=chunk.token_count,
                                )
                            )
                    job.status = IngestionJobStatus.succeeded
                    job.completed_units = len(result.chunks)
                    job.total_units = len(result.chunks)
                    job.last_error_code = None
                    job.last_error_message = None
                    error = None
                lease.lease_expires_at = now
                session.add(
                    IngestionJobAttempt(
                        organization_id=claim.organization_id,
                        project_id=claim.project_id,
                        job_id=claim.job_id,
                        attempt_number=claim.attempt_number,
                        worker_id=claim.worker_id,
                        final_status=final_status,
                        started_at=claim.started_at,
                        finished_at=now,
                        input_snapshot={
                            "document_version_id": str(claim.document_version_id),
                            "sha256": claim.sha256,
                            "byte_size": claim.byte_size,
                        },
                        error_code=error.code if error is not None else None,
                        error_message=error.message if error is not None else None,
                        retryable=error.retryable if error is not None else False,
                        fencing_token=claim.fencing_token,
                    )
                )
                record_audit_event(
                    session,
                    organization_id=claim.organization_id,
                    project_id=claim.project_id,
                    actor_id=SYSTEM_ACTOR_ID,
                    action=(
                        "ingestion.cancelled"
                        if final_status is IngestionAttemptFinalStatus.cancelled
                        else "ingestion.failed"
                        if final_status is IngestionAttemptFinalStatus.failed
                        else "ingestion.succeeded"
                    ),
                    resource_type="ingestion_job",
                    resource_id=str(claim.job_id),
                    metadata={
                        "worker_id": claim.worker_id,
                        "attempt_number": claim.attempt_number,
                        "fencing_token": claim.fencing_token,
                        "error_code": error.code if error is not None else None,
                    },
                )
                return final_status

    @staticmethod
    def _lease_is_current(lease: IngestionJobLease, claim: _Claim) -> bool:
        return (
            lease.id == claim.lease_id
            and lease.job_id == claim.job_id
            and lease.worker_id == claim.worker_id
            and lease.attempt_number == claim.attempt_number
            and lease.fencing_token == claim.fencing_token
            and lease.lease_expires_at > datetime.now(UTC)
        )
