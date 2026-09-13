"""Durable worker for provider-backed candidate generation jobs."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_eval_api.candidates.protocol import (
    CandidateChunk,
    CandidateGenerationRequest,
    CandidateGenerationResult,
    CandidateGenerator,
)
from rag_eval_api.models import (
    CandidateDataset,
    CandidateDatasetItem,
    CandidateDatasetStatus,
    CandidateDatasetVersion,
    CandidateGenerationConfig,
    CandidateItemEvidence,
    CandidateReviewStatus,
    DocumentChunk,
    IngestionAttemptFinalStatus,
    IngestionJob,
    IngestionJobAttempt,
    IngestionJobKind,
    IngestionJobLease,
    IngestionJobStatus,
)
from rag_eval_api.services.ingestion_jobs import IngestionJobState

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Claim:
    job_id: UUID
    organization_id: UUID
    project_id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    source_version_id: UUID
    dataset_name: str
    config_id: UUID
    capability_version: str
    provider_name: str
    prompt_version: str
    parser_version: str | None
    seed: int | None
    randomness: float
    request_id: str
    chunks: tuple[CandidateChunk, ...]
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
class CandidateWorkerBatchResult:
    """Counters for one bounded generation-worker batch."""

    processed: int
    succeeded: int
    failed: int
    cancelled: int
    lease_lost: int = 0


class CandidateWorker:
    """Claim and execute only ``generate_candidates`` jobs."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        generator: CandidateGenerator,
        worker_id: str,
        lease_ttl: timedelta = timedelta(seconds=60),
        batch_size: int = 1,
        heartbeat_interval: timedelta | None = None,
    ) -> None:
        if not worker_id.strip() or len(worker_id) > 255:
            raise ValueError("worker_id must be 1 to 255 characters")
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        interval = heartbeat_interval or lease_ttl / 3
        if interval <= timedelta(0) or interval >= lease_ttl:
            raise ValueError("heartbeat_interval must be positive and less than lease_ttl")
        self.session_factory = session_factory
        self.generator = generator
        self.worker_id = worker_id
        self.lease_ttl = lease_ttl
        self.batch_size = batch_size
        self.heartbeat_interval = interval
        self._shutdown_requested = False
        self._active_task: asyncio.Task[Any] | None = None

    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        if self._active_task is not None and not self._active_task.done():
            self._active_task.cancel()

    async def run_once(self) -> bool:
        return await self._process_one() is not None

    async def process_batch(self, limit: int) -> CandidateWorkerBatchResult:
        if limit < 1:
            raise ValueError("limit must be positive")
        outcomes: list[str] = []
        for _ in range(limit):
            outcome = await self._process_one()
            if outcome is None:
                break
            outcomes.append(outcome)
        return CandidateWorkerBatchResult(
            processed=len(outcomes),
            succeeded=outcomes.count(IngestionAttemptFinalStatus.succeeded.value),
            failed=outcomes.count(IngestionAttemptFinalStatus.failed.value),
            cancelled=outcomes.count(IngestionAttemptFinalStatus.cancelled.value),
            lease_lost=outcomes.count("lease_lost"),
        )

    async def run_maintenance(self) -> None:
        """Requeue expired generation leases; PostgreSQL remains the source of truth."""

        now = datetime.now(UTC)
        async with self.session_factory() as session:
            async with session.begin():
                leases = list(
                    (
                        await session.scalars(
                            select(IngestionJobLease)
                            .where(IngestionJobLease.lease_expires_at <= now)
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
                            IngestionJob.job_kind == IngestionJobKind.generate_candidates,
                        )
                        .with_for_update()
                    )
                    if job is not None and job.status is IngestionJobStatus.processing:
                        IngestionJobState.recover_target(job.status.value)
                        job.status = IngestionJobStatus.queued
                        LOGGER.info(
                            "candidate generation job requeued after lease expiry",
                            extra={"event": "candidate_worker.job_requeued", "job_id": str(job.id)},
                        )

    async def _claim_next(self) -> _Claim | None:
        async with self.session_factory() as session:
            async with session.begin():
                job = (
                    await session.scalars(
                        select(IngestionJob)
                        .where(
                            IngestionJob.job_kind == IngestionJobKind.generate_candidates,
                            IngestionJob.status == IngestionJobStatus.queued,
                        )
                        .order_by(IngestionJob.created_at, IngestionJob.id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                ).first()
                if job is None:
                    return None
                required = (
                    job.candidate_dataset_id,
                    job.candidate_dataset_version_id,
                    job.source_version_id,
                    job.generation_config_id,
                )
                if any(value is None for value in required):
                    raise RuntimeError("generation job references are incomplete")
                dataset_id, dataset_version_id, source_version_id, config_id = required
                assert dataset_id is not None
                assert dataset_version_id is not None
                assert source_version_id is not None
                assert config_id is not None
                now = datetime.now(UTC)
                lease = await session.scalar(
                    select(IngestionJobLease)
                    .where(IngestionJobLease.job_id == job.id)
                    .with_for_update()
                )
                if lease is not None and lease.lease_expires_at > now:
                    return None
                config = await session.scalar(
                    select(CandidateGenerationConfig).where(
                        CandidateGenerationConfig.id == config_id,
                        CandidateGenerationConfig.dataset_id == dataset_id,
                        CandidateGenerationConfig.organization_id == job.organization_id,
                        CandidateGenerationConfig.project_id == job.project_id,
                    )
                )
                if config is None:
                    raise RuntimeError("generation configuration is unavailable")
                dataset = await session.scalar(
                    select(CandidateDataset).where(
                        CandidateDataset.id == dataset_id,
                        CandidateDataset.organization_id == job.organization_id,
                        CandidateDataset.project_id == job.project_id,
                    )
                )
                if dataset is None or dataset.status is CandidateDatasetStatus.archived:
                    raise RuntimeError("candidate dataset is unavailable")
                chunks = list(
                    (
                        await session.scalars(
                            select(DocumentChunk)
                            .where(
                                DocumentChunk.document_version_id == source_version_id,
                                DocumentChunk.organization_id == job.organization_id,
                                DocumentChunk.project_id == job.project_id,
                            )
                            .order_by(DocumentChunk.ordinal, DocumentChunk.id)
                        )
                    ).all()
                )
                if not chunks:
                    raise RuntimeError("generation source has no chunks")
                attempt_number = job.attempt_count + 1
                fencing_token = lease.fencing_token + 1 if lease is not None else 1
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
                IngestionJobState.transition(job.status.value, IngestionJobStatus.processing.value)
                job.status = IngestionJobStatus.processing
                job.attempt_count = attempt_number
                job.completed_units = 0
                job.last_error_code = None
                job.last_error_message = None
                await session.flush()
                return _Claim(
                    job_id=job.id,
                    organization_id=job.organization_id,
                    project_id=job.project_id,
                    dataset_id=dataset_id,
                    dataset_version_id=dataset_version_id,
                    source_version_id=source_version_id,
                    dataset_name=dataset.name,
                    config_id=config_id,
                    capability_version=config.capability_version,
                    provider_name=config.provider_name,
                    prompt_version=config.prompt_version,
                    parser_version=config.parser_version,
                    seed=config.seed,
                    randomness=config.randomness,
                    request_id=config.request_id,
                    chunks=tuple(
                        CandidateChunk(
                            chunk_id=chunk.id,
                            ordinal=chunk.ordinal,
                            content=chunk.content,
                            content_hash=chunk.content_hash,
                            source_location=chunk.source_location,
                        )
                        for chunk in chunks
                    ),
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
        result: CandidateGenerationResult | None = None
        try:
            request = CandidateGenerationRequest(
                document_version_id=claim.source_version_id,
                dataset_name=claim.dataset_name,
                capability_version=claim.capability_version,
                prompt_version=claim.prompt_version,
                parser_version=claim.parser_version,
                seed=claim.seed,
                randomness=claim.randomness,
                chunks=claim.chunks,
                request_id=claim.request_id,
            )
            generation_task = asyncio.create_task(
                asyncio.to_thread(self.generator.generate, request)
            )
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(claim))
            self._active_task = generation_task
            try:
                done, _ = await asyncio.wait(
                    {generation_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if heartbeat_task in done:
                    await heartbeat_task
                result = await generation_task
            finally:
                self._active_task = None
                for task in (generation_task, heartbeat_task):
                    if not task.done():
                        task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
        except Exception as exc:
            failure = self._classify_failure(exc)
        except asyncio.CancelledError:
            failure = _Failure("cancelled", "Candidate generation was cancelled.", False)
        final = await self._finalize(claim, result=result, failure=failure)
        if final is None:
            return "lease_lost"
        return final.value

    async def _heartbeat_loop(self, claim: _Claim) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval.total_seconds())
            if not await self.heartbeat(claim):
                raise RuntimeError("lease_lost")

    async def heartbeat(self, claim: _Claim) -> bool:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            async with session.begin():
                updated = await session.execute(
                    update(IngestionJobLease)
                    .where(
                        IngestionJobLease.id == claim.lease_id,
                        IngestionJobLease.job_id == claim.job_id,
                        IngestionJobLease.fencing_token == claim.fencing_token,
                        IngestionJobLease.lease_expires_at > now,
                    )
                    .values(heartbeat_at=now, lease_expires_at=now + self.lease_ttl)
                )
                if updated.rowcount != 1:
                    return False
                job = await session.scalar(
                    select(IngestionJob).where(IngestionJob.id == claim.job_id)
                )
                return (
                    job is not None
                    and job.status is IngestionJobStatus.processing
                    and job.cancel_requested_at is None
                )

    async def _finalize(
        self,
        claim: _Claim,
        *,
        result: CandidateGenerationResult | None,
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
                    .where(IngestionJobLease.job_id == claim.job_id)
                    .with_for_update()
                )
                if job is None or lease is None or not self._lease_is_current(lease, claim):
                    return None
                now = datetime.now(UTC)
                cancelled = (
                    job.status is IngestionJobStatus.cancelled
                    or job.cancel_requested_at is not None
                )
                if cancelled:
                    final_status = IngestionAttemptFinalStatus.cancelled
                    error = _Failure("cancelled", "Candidate generation was cancelled.", False)
                    job.status = IngestionJobStatus.cancelled
                elif failure is not None:
                    final_status = IngestionAttemptFinalStatus.failed
                    error = failure
                    job.status = IngestionJobStatus.failed
                else:
                    assert result is not None
                    if result.capability_version != claim.capability_version:
                        error = _Failure(
                            "invalid_provider_output", "Provider output was invalid.", False
                        )
                        final_status = IngestionAttemptFinalStatus.failed
                        job.status = IngestionJobStatus.failed
                    else:
                        if result.provider_name != claim.provider_name:
                            error = _Failure(
                                "invalid_provider_output", "Provider output was invalid.", False
                            )
                            final_status = IngestionAttemptFinalStatus.failed
                            job.status = IngestionJobStatus.failed
                        else:
                            for draft in result.items:
                                item = CandidateDatasetItem(
                                    organization_id=claim.organization_id,
                                    project_id=claim.project_id,
                                    dataset_id=claim.dataset_id,
                                    dataset_version_id=claim.dataset_version_id,
                                    generation_config_id=claim.config_id,
                                    source_version_id=claim.source_version_id,
                                    question=draft.question,
                                    question_type=draft.question_type,
                                    reference_answer=draft.reference_answer,
                                    confidence=draft.confidence,
                                    automatic_checks=draft.automatic_checks,
                                    review_status=CandidateReviewStatus.pending,
                                    provenance=draft.provenance,
                                )
                                session.add(item)
                                await session.flush()
                                for evidence in draft.evidence:
                                    session.add(
                                        CandidateItemEvidence(
                                            organization_id=claim.organization_id,
                                            project_id=claim.project_id,
                                            item_id=item.id,
                                            source_version_id=claim.source_version_id,
                                            chunk_id=evidence.chunk_id,
                                            ordinal=evidence.ordinal,
                                            excerpt=evidence.excerpt,
                                        )
                                    )
                            version = await session.scalar(
                                select(CandidateDatasetVersion)
                                .where(
                                    CandidateDatasetVersion.id == claim.dataset_version_id,
                                    CandidateDatasetVersion.dataset_id == claim.dataset_id,
                                    CandidateDatasetVersion.organization_id
                                    == claim.organization_id,
                                    CandidateDatasetVersion.project_id == claim.project_id,
                                )
                                .with_for_update()
                            )
                            if version is None:
                                error = _Failure(
                                    "generation_job_invalid",
                                    "Dataset version is unavailable.",
                                    False,
                                )
                                final_status = IngestionAttemptFinalStatus.failed
                                job.status = IngestionJobStatus.failed
                            else:
                                version.item_count = len(result.items)
                                version.status = CandidateDatasetStatus.review
                                job.completed_units = len(result.items)
                                job.total_units = len(result.items)
                                job.status = IngestionJobStatus.succeeded
                                error = None
                                final_status = IngestionAttemptFinalStatus.succeeded
                lease.lease_expires_at = now
                job.last_error_code = error.code if error is not None else None
                job.last_error_message = error.message if error is not None else None
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
                            "source_version_id": str(claim.source_version_id),
                            "generation_config_id": str(claim.config_id),
                            "chunk_count": len(claim.chunks),
                        },
                        error_code=error.code if error is not None else None,
                        error_message=error.message if error is not None else None,
                        retryable=error.retryable if error is not None else False,
                        fencing_token=claim.fencing_token,
                    )
                )
                return final_status

    @staticmethod
    def _classify_failure(exc: Exception) -> _Failure:
        if isinstance(exc, RuntimeError) and str(exc) == "lease_lost":
            return _Failure("lease_lost", "Worker lease could not be renewed.", True)
        code = (
            str(exc)
            if str(exc) in {"provider_timeout", "invalid_provider_output"}
            else "generation_failed"
        )
        return _Failure(code, "Candidate generation failed safely.", code == "provider_timeout")

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
