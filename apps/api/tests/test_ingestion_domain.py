from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from rag_eval_api.services.ingestion_jobs import (
    INGESTION_ERROR_CODES,
    IdempotencyConflict,
    IngestionJobState,
    InvalidJobTransition,
    LeaseConflict,
    LeaseManager,
    ensure_idempotency,
)


def test_job_state_machine_accepts_only_documented_transitions() -> None:
    assert IngestionJobState.transition("queued", "processing") == "processing"
    assert IngestionJobState.transition("processing", "partial") == "partial"
    assert IngestionJobState.transition("blocked", "queued") == "queued"

    with pytest.raises(InvalidJobTransition):
        IngestionJobState.transition("succeeded", "processing")
    with pytest.raises(InvalidJobTransition):
        IngestionJobState.transition("unknown", "processing")
    with pytest.raises(InvalidJobTransition):
        IngestionJobState.transition("processing", "queued")


def test_retry_requires_retryable_failure_or_explicit_blocked_resolution() -> None:
    assert IngestionJobState.retry_target("failed", retryable=True) == "queued"
    assert IngestionJobState.retry_target("blocked", retryable=False) == "queued"

    with pytest.raises(InvalidJobTransition):
        IngestionJobState.retry_target("failed", retryable=False)
    with pytest.raises(InvalidJobTransition):
        IngestionJobState.retry_target("cancelled", retryable=True)
    with pytest.raises(InvalidJobTransition):
        IngestionJobState.retry_target("succeeded", retryable=True)


def test_cancel_and_block_follow_terminal_and_provider_configuration_rules() -> None:
    assert IngestionJobState.cancel_target("queued") == "cancelled"
    assert IngestionJobState.cancel_target("processing") == "cancelled"
    assert IngestionJobState.block_target("processing") == "blocked"

    with pytest.raises(InvalidJobTransition):
        IngestionJobState.cancel_target("succeeded")


def test_idempotency_replay_is_allowed_but_fingerprint_conflict_is_rejected() -> None:
    scope = (uuid4(), "parse", "request-1")
    assert ensure_idempotency(scope, "fingerprint-a", "fingerprint-a") is None

    with pytest.raises(IdempotencyConflict):
        ensure_idempotency(scope, "fingerprint-b", "fingerprint-a")
    assert {
        "duplicate_document",
        "idempotency_conflict",
        "parse_timeout",
        "parser_sandbox_unavailable",
    } <= INGESTION_ERROR_CODES


def test_lease_claim_heartbeat_and_fencing_reject_stale_workers() -> None:
    manager = LeaseManager(ttl=timedelta(seconds=30))
    now = datetime(2026, 1, 1, tzinfo=UTC)
    job_id = uuid4()
    first = manager.claim(job_id, "worker-a", now=now)
    assert first.fencing_token == 1
    assert manager.heartbeat(
        job_id, "worker-a", first.fencing_token, now=now + timedelta(seconds=1)
    )

    with pytest.raises(LeaseConflict):
        manager.claim(job_id, "worker-b", now=now + timedelta(seconds=2))
    with pytest.raises(LeaseConflict):
        manager.assert_fencing_token(job_id, "worker-a", fencing_token=0, now=now)

    second = manager.claim(job_id, "worker-b", now=now + timedelta(seconds=31))
    assert second.fencing_token == 2
    with pytest.raises(LeaseConflict):
        manager.heartbeat(job_id, "worker-a", first.fencing_token, now=now + timedelta(seconds=32))
