"""Recoverable, one-item-at-a-time experiment execution worker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_eval_api.adapters import Adapter, AdapterRequest
from rag_eval_api.adapters.errors import AdapterError
from rag_eval_api.models import (
    AdapterConfig,
    CandidateDatasetItem,
    Experiment,
    ExperimentRun,
    ExperimentRunAttempt,
    ExperimentRunItem,
    ExperimentRunItemStatus,
    ExperimentRunStatus,
    ExperimentStatus,
)

LOGGER = logging.getLogger(__name__)
AdapterFactory = Callable[[AdapterConfig], Adapter]


@dataclass(frozen=True, slots=True)
class ExperimentWorkerResult:
    processed: int
    succeeded: int
    failed: int
    cancelled: int
    lease_lost: int = 0


@dataclass(frozen=True, slots=True)
class _Claim:
    run_id: UUID
    run_item_id: UUID
    experiment_id: UUID
    organization_id: UUID
    project_id: UUID
    candidate_item_id: UUID
    question: str
    timeout_seconds: float
    attempt_number: int
    fencing_token: int
    worker_id: str


class ExperimentWorker:
    """Execute queued experiment items behind a renewable run lease."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        adapter_factory: AdapterFactory,
        worker_id: str,
        lease_ttl: timedelta = timedelta(seconds=60),
    ) -> None:
        if not worker_id.strip() or len(worker_id) > 255:
            raise ValueError("worker_id must be 1 to 255 characters")
        if lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")
        self.session_factory = session_factory
        self.adapter_factory = adapter_factory
        self.worker_id = worker_id
        self.lease_ttl = lease_ttl
        self._shutdown_requested = False

    def request_shutdown(self) -> None:
        self._shutdown_requested = True

    async def process_batch(self, limit: int) -> ExperimentWorkerResult:
        if limit < 1:
            raise ValueError("limit must be positive")
        outcomes: list[str] = []
        for _ in range(limit):
            outcome = await self._process_one()
            if outcome is None:
                break
            outcomes.append(outcome)
        return ExperimentWorkerResult(
            processed=len(outcomes),
            succeeded=outcomes.count("succeeded"),
            failed=outcomes.count("failed"),
            cancelled=outcomes.count("cancelled"),
            lease_lost=outcomes.count("lease_lost"),
        )

    async def run_maintenance(self) -> None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            async with session.begin():
                runs = list(
                    (
                        await session.scalars(
                            select(ExperimentRun)
                            .where(
                                ExperimentRun.lease_expires_at <= now,
                                ExperimentRun.status == ExperimentRunStatus.running,
                            )
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                for run in runs:
                    run.status = ExperimentRunStatus.queued
                    run.worker_id = None
                    run.lease_expires_at = None
                    run.heartbeat_at = None

    async def _claim_next(self) -> _Claim | None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            async with session.begin():
                run = (
                    await session.scalars(
                        select(ExperimentRun)
                        .where(
                            ExperimentRun.status.in_([ExperimentRunStatus.queued, ExperimentRunStatus.running]),
                            (
                                (ExperimentRun.status == ExperimentRunStatus.queued)
                                | (ExperimentRun.worker_id == self.worker_id)
                                | (ExperimentRun.lease_expires_at <= now)
                            ),
                        )
                        .order_by(ExperimentRun.created_at, ExperimentRun.id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                ).first()
                if run is None:
                    return None
                item = await session.scalar(
                    select(ExperimentRunItem)
                    .where(
                        ExperimentRunItem.run_id == run.id,
                        ExperimentRunItem.organization_id == run.organization_id,
                        ExperimentRunItem.project_id == run.project_id,
                        ExperimentRunItem.status == ExperimentRunItemStatus.queued,
                    )
                    .order_by(ExperimentRunItem.created_at, ExperimentRunItem.id)
                    .with_for_update()
                )
                if item is None:
                    if run.status is ExperimentRunStatus.running:
                        run.status = ExperimentRunStatus.succeeded if run.failed_units == 0 else ExperimentRunStatus.failed
                        run.completed_at = now
                    elif run.status is ExperimentRunStatus.cancelling:
                        run.status = ExperimentRunStatus.cancelled
                        run.completed_at = now
                        experiment = await session.get(Experiment, run.experiment_id)
                        if experiment is not None:
                            experiment.status = ExperimentStatus.cancelled
                            experiment.completed_at = now
                    return None
                experiment = await session.scalar(
                    select(Experiment).where(
                        Experiment.id == run.experiment_id,
                        Experiment.organization_id == run.organization_id,
                        Experiment.project_id == run.project_id,
                    )
                )
                if experiment is None:
                    raise RuntimeError("experiment run references are incomplete")
                adapter = await session.scalar(
                    select(AdapterConfig).where(
                        AdapterConfig.id == experiment.adapter_config_id,
                        AdapterConfig.organization_id == run.organization_id,
                        AdapterConfig.project_id == run.project_id,
                    )
                )
                candidate = await session.scalar(
                    select(CandidateDatasetItem).where(
                        CandidateDatasetItem.id == item.candidate_item_id,
                        CandidateDatasetItem.organization_id == run.organization_id,
                        CandidateDatasetItem.project_id == run.project_id,
                    )
                )
                if adapter is None or candidate is None:
                    raise RuntimeError("experiment run references are incomplete")
                token = run.fencing_token + 1
                run.status = ExperimentRunStatus.running
                run.worker_id = self.worker_id
                run.lease_expires_at = now + self.lease_ttl
                run.heartbeat_at = now
                run.fencing_token = token
                item.status = ExperimentRunItemStatus.processing
                item.attempt_count += 1
                item.started_at = now
                await session.flush()
                return _Claim(
                    run_id=run.id,
                    run_item_id=item.id,
                    experiment_id=run.experiment_id,
                    organization_id=run.organization_id,
                    project_id=run.project_id,
                    candidate_item_id=candidate.id,
                    question=candidate.question,
                    timeout_seconds=adapter.timeout_seconds,
                    attempt_number=item.attempt_count,
                    fencing_token=token,
                    worker_id=self.worker_id,
                )

    async def _process_one(self) -> str | None:
        claim = await self._claim_next()
        if claim is None:
            return None
        status = "succeeded"
        response: Any = None
        error_code: str | None = None
        error_message: str | None = None
        try:
            async with self.session_factory() as session:
                adapter_config = await session.scalar(
                    select(AdapterConfig).where(
                        AdapterConfig.organization_id == claim.organization_id,
                        AdapterConfig.project_id == claim.project_id,
                        AdapterConfig.id == (
                            select(Experiment.adapter_config_id).where(Experiment.id == claim.experiment_id).scalar_subquery()
                        ),
                    )
                )
            if adapter_config is None:
                raise AdapterError("adapter_unavailable", "Adapter configuration is unavailable.")
            adapter = self.adapter_factory(adapter_config)
            request = AdapterRequest(
                request_id=str(uuid4()),
                question=claim.question,
                timeout_seconds=claim.timeout_seconds,
                metadata={"run_id": str(claim.run_id), "run_item_id": str(claim.run_item_id)},
            )
            response = await asyncio.wait_for(
                asyncio.to_thread(adapter.run, request), timeout=claim.timeout_seconds
            )
        except TimeoutError:
            status = "failed"
            error_code, error_message = "adapter_timeout", "Adapter request timed out."
        except AdapterError as exc:
            status = "failed"
            error_code, error_message = exc.code, "Adapter request failed safely."
        except Exception:
            LOGGER.exception("experiment run item failed", extra={"event": "experiment.item_failed", "run_item_id": str(claim.run_item_id)})
            status = "failed"
            error_code, error_message = "adapter_error", "Adapter request failed safely."
        return await self._finish(claim, status, response, error_code, error_message)

    async def _finish(
        self,
        claim: _Claim,
        status: str,
        response: Any,
        error_code: str | None,
        error_message: str | None,
    ) -> str:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            async with session.begin():
                run = await session.scalar(
                    select(ExperimentRun)
                    .where(
                        ExperimentRun.id == claim.run_id,
                        ExperimentRun.organization_id == claim.organization_id,
                        ExperimentRun.project_id == claim.project_id,
                        ExperimentRun.worker_id == claim.worker_id,
                        ExperimentRun.fencing_token == claim.fencing_token,
                        ExperimentRun.lease_expires_at > now,
                    )
                    .with_for_update()
                )
                if run is None:
                    return "lease_lost"
                item = await session.scalar(
                    select(ExperimentRunItem).where(
                        ExperimentRunItem.id == claim.run_item_id,
                        ExperimentRunItem.run_id == claim.run_id,
                        ExperimentRunItem.organization_id == claim.organization_id,
                        ExperimentRunItem.project_id == claim.project_id,
                    )
                )
                if item is None:
                    return "lease_lost"
                cancelled = run.status is ExperimentRunStatus.cancelling
                final_status = (
                    ExperimentRunItemStatus.cancelled
                    if cancelled
                    else ExperimentRunItemStatus.succeeded
                    if status == "succeeded"
                    else ExperimentRunItemStatus.failed
                )
                item.status = final_status
                item.completed_at = now
                item.error_code = error_code
                item.error_message = error_message
                if response is not None and not cancelled:
                    item.final_answer = response.answer
                    item.final_usage = response.usage.model_dump(mode="json")
                    item.final_latency_ms = response.usage.latency_ms
                    item.final_trace_id = response.trace.trace_id if response.trace else None
                session.add(
                    ExperimentRunAttempt(
                        organization_id=claim.organization_id,
                        project_id=claim.project_id,
                        run_item_id=item.id,
                        attempt_number=claim.attempt_number,
                        status=final_status,
                        usage=item.final_usage,
                        latency_ms=item.final_latency_ms,
                        trace_id=item.final_trace_id,
                        error_code=error_code,
                        error_message=error_message,
                        created_at=now,
                    )
                )
                run.completed_units += 1
                if final_status is ExperimentRunItemStatus.succeeded:
                    run.succeeded_units += 1
                elif final_status is ExperimentRunItemStatus.failed:
                    run.failed_units += 1
                else:
                    run.skipped_units += 1
                remaining = await session.scalar(
                    select(func.count(ExperimentRunItem.id)).where(
                        ExperimentRunItem.run_id == run.id,
                        ExperimentRunItem.status.in_([ExperimentRunItemStatus.queued, ExperimentRunItemStatus.processing]),
                    )
                )
                if remaining == 0:
                    run.status = (
                        ExperimentRunStatus.cancelled
                        if cancelled
                        else ExperimentRunStatus.succeeded
                        if run.failed_units == 0
                        else ExperimentRunStatus.failed
                    )
                    run.completed_at = now
                    experiment = await session.get(Experiment, run.experiment_id)
                    if experiment is not None:
                        experiment.status = (
                            ExperimentStatus.cancelled
                            if cancelled
                            else ExperimentStatus.succeeded
                            if run.failed_units == 0
                            else ExperimentStatus.failed
                        )
                        experiment.completed_units = run.completed_units
                        experiment.succeeded_units = run.succeeded_units
                        experiment.failed_units = run.failed_units
                        experiment.completed_at = now
                else:
                    run.lease_expires_at = now + self.lease_ttl
                    run.heartbeat_at = now
        return status
