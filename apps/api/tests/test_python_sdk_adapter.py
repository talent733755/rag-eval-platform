from __future__ import annotations

import time

import pytest

from rag_eval_api.adapters.errors import AdapterError, AdapterUnavailableError
from rag_eval_api.adapters.protocol import AdapterRequest, AdapterResponse
from rag_eval_api.adapters.python_sdk import PythonSdkAdapter


def fixture_entrypoint(request: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": request["request_id"],
        "answer": "fixture answer",
        "usage": {"latency_ms": 1},
    }


def slow_entrypoint(request: dict[str, object]) -> dict[str, object]:
    del request
    time.sleep(1)
    return {"request_id": "request-1", "answer": "late", "usage": {"latency_ms": 1000}}


def oversized_entrypoint(request: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": request["request_id"],
        "answer": "x" * 1000,
        "usage": {"latency_ms": 1},
    }


def request() -> AdapterRequest:
    return AdapterRequest(request_id="request-1", question="问题", timeout_seconds=2)


def test_python_sdk_adapter_runs_only_the_versioned_entrypoint() -> None:
    adapter = PythonSdkAdapter(
        fixture_entrypoint,
        adapter_version="fixture-1",
        trace_level="minimal",
        timeout_seconds=1,
    )

    response = adapter.run(request())

    assert isinstance(response, AdapterResponse)
    assert response.request_id == "request-1"
    assert response.answer == "fixture answer"
    assert adapter.capability.adapter_version == "fixture-1"


def test_python_sdk_adapter_classifies_timeout_and_kills_child() -> None:
    adapter = PythonSdkAdapter(
        slow_entrypoint,
        adapter_version="fixture-1",
        trace_level="none",
        timeout_seconds=0.05,
    )

    with pytest.raises(AdapterUnavailableError) as error:
        adapter.run(request())

    assert getattr(error.value, "code") == "adapter_timeout"


def test_python_sdk_adapter_rejects_oversized_or_invalid_response() -> None:
    adapter = PythonSdkAdapter(
        oversized_entrypoint,
        adapter_version="fixture-1",
        trace_level="full",
        timeout_seconds=1,
        max_response_bytes=128,
    )

    with pytest.raises(AdapterError) as error:
        adapter.run(request())

    assert getattr(error.value, "code") == "adapter_response_too_large"
