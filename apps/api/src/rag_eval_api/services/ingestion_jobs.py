"""Pure job-state, idempotency, and lease domain primitives.

This module deliberately has no database or API dependency. A later repository/worker
layer can persist these decisions transactionally without allowing routes to invent
state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

INGESTION_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "unsupported_type",
        "size_exceeded",
        "parse_timeout",
        "parser_sandbox_unavailable",
        "security_violation",
        "checksum_mismatch",
        "blob_already_exists",
        "blob_security_error",
        "invalid_storage_key",
        "blob_not_found",
        "blob_store_error",
        "parse_failed",
        "provider_not_configured",
        "provider_timeout",
        "provider_invalid_output",
        "cancelled",
        "duplicate_document",
        "lease_lost",
        "idempotency_conflict",
    }
)


class InvalidJobTransition(ValueError):
    """Raised when a job state transition is not part of the public contract."""


class IdempotencyConflict(ValueError):
    """Raised when a key is reused with a different canonical request fingerprint."""


class LeaseConflict(RuntimeError):
    """Raised when a worker cannot claim or fence a job lease."""


class IngestionJobState:
    """Allowed durable job state transitions and retry policy."""

    _TRANSITIONS: Final[dict[str, frozenset[str]]] = {
        "queued": frozenset({"processing", "cancelled"}),
        "processing": frozenset({"succeeded", "partial", "failed", "blocked", "cancelled"}),
        "blocked": frozenset({"queued", "cancelled"}),
        "succeeded": frozenset(),
        "partial": frozenset(),
        "failed": frozenset(),
        "cancelled": frozenset(),
    }

    @classmethod
    def transition(cls, current: str, target: str) -> str:
        if target not in cls._TRANSITIONS.get(current, frozenset()):
            raise InvalidJobTransition(
                f"cannot transition ingestion job from {current} to {target}"
            )
        return target

    @classmethod
    def retry_target(cls, current: str, *, retryable: bool) -> str:
        if current == "blocked":
            return cls.transition(current, "queued")
        if current in {"failed", "partial"} and retryable:
            return "queued"
        raise InvalidJobTransition(f"job in {current} cannot be retried")

    @classmethod
    def cancel_target(cls, current: str) -> str:
        """Return the terminal cancellation state for a cancellable job."""

        return cls.transition(current, "cancelled")

    @classmethod
    def block_target(cls, current: str) -> str:
        """Return the blocked state used for configuration or capability failures."""

        return cls.transition(current, "blocked")


def ensure_idempotency(
    scope: tuple[UUID, str, str], fingerprint: str, existing_fingerprint: str | None
) -> None:
    """Allow a request replay and reject a same-key request with different input."""

    del scope
    if existing_fingerprint is not None and existing_fingerprint != fingerprint:
        raise IdempotencyConflict("idempotency key was already used with a different request")


@dataclass(frozen=True, slots=True)
class Lease:
    job_id: UUID
    worker_id: str
    attempt_number: int
    fencing_token: int
    lease_expires_at: datetime
    heartbeat_at: datetime


class LeaseManager:
    """Small deterministic lease authority used by repositories and unit tests.

    The database implementation must mirror these rules using a row lock and a
    conditional fencing-token update. A worker may never write a result after its
    token or lease has become stale.
    """

    def __init__(self, *, ttl: timedelta) -> None:
        if ttl <= timedelta(0):
            raise ValueError("lease TTL must be positive")
        self._ttl = ttl
        self._leases: dict[UUID, Lease] = {}
        self._next_attempt: dict[UUID, int] = {}
        self._next_token: dict[UUID, int] = {}

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        current = value or datetime.now(UTC)
        return current if current.tzinfo is not None else current.replace(tzinfo=UTC)

    def claim(self, job_id: UUID, worker_id: str, *, now: datetime | None = None) -> Lease:
        current_time = self._utc(now)
        current = self._leases.get(job_id)
        if current is not None and current.lease_expires_at > current_time:
            raise LeaseConflict("job already has an active lease")
        attempt = self._next_attempt.get(job_id, 0) + 1
        token = self._next_token.get(job_id, 0) + 1
        lease = Lease(
            job_id=job_id,
            worker_id=worker_id,
            attempt_number=attempt,
            fencing_token=token,
            lease_expires_at=current_time + self._ttl,
            heartbeat_at=current_time,
        )
        self._leases[job_id] = lease
        self._next_attempt[job_id] = attempt
        self._next_token[job_id] = token
        return lease

    def heartbeat(
        self, job_id: UUID, worker_id: str, fencing_token: int, *, now: datetime | None = None
    ) -> Lease:
        current_time = self._utc(now)
        lease = self._require_current(job_id, worker_id, fencing_token, current_time)
        refreshed = Lease(
            job_id=lease.job_id,
            worker_id=lease.worker_id,
            attempt_number=lease.attempt_number,
            fencing_token=lease.fencing_token,
            lease_expires_at=current_time + self._ttl,
            heartbeat_at=current_time,
        )
        self._leases[job_id] = refreshed
        return refreshed

    def assert_fencing_token(
        self,
        job_id: UUID,
        worker_id: str,
        fencing_token: int,
        *,
        now: datetime | None = None,
    ) -> None:
        self._require_current(job_id, worker_id, fencing_token, self._utc(now))

    def _require_current(
        self, job_id: UUID, worker_id: str, fencing_token: int, now: datetime
    ) -> Lease:
        lease = self._leases.get(job_id)
        if (
            lease is None
            or lease.worker_id != worker_id
            or lease.fencing_token != fencing_token
            or lease.lease_expires_at <= now
        ):
            raise LeaseConflict("worker lease is stale or fenced")
        return lease
