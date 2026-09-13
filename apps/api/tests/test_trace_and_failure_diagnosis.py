from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from rag_eval_api.services.failure_diagnosis import classify_failure
from rag_eval_api.traces.protocol import TraceRecord


def test_trace_record_is_bounded_and_rejects_duplicate_stages() -> None:
    stage = {
        "name": "retrieve",
        "started_at": datetime.now(UTC),
        "payload_hash": "a" * 64,
        "payload": {"ids": ["chunk-1"]},
    }
    with pytest.raises(ValidationError):
        TraceRecord(
            trace_version="trace-v1",
            trace_id="t",
            run_item_id="r",
            level="full",
            stages=(stage, stage),
        )


def test_failure_diagnosis_has_stable_precedence_and_safe_messages() -> None:
    result = classify_failure(timed_out=True, adapter_error=True, relevant_retrieved=False)
    assert result is not None
    assert result.code == "timeout"
    assert result.retryable is True
    assert "API" not in result.safe_message

    assert (
        classify_failure(relevant_retrieved=False, citations_valid=False).code == "retrieval_miss"
    )  # type: ignore[union-attr]
    assert classify_failure() is None
