import pytest
from pydantic import ValidationError

from rag_eval_api.adapters.protocol import (
    ADAPTER_CAPABILITY_VERSION,
    AdapterCapability,
    AdapterRequest,
    AdapterResponse,
)


def test_adapter_protocol_accepts_traceable_response() -> None:
    response = AdapterResponse.model_validate(
        {
            "request_id": "run-item-1",
            "answer": "答案",
            "citations": [
                {"source_id": "version-1", "chunk_id": "chunk-1", "ordinal": 0, "quote": "证据"}
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "latency_ms": 42},
            "trace": {
                "trace_id": "trace-1",
                "level": "minimal",
                "stages": {"retrieve": {"count": 1}},
            },
        }
    )
    assert response.request_id == "run-item-1"
    assert ADAPTER_CAPABILITY_VERSION == "adapter-v1"


def test_adapter_request_rejects_unbounded_or_empty_context() -> None:
    with pytest.raises(ValidationError):
        AdapterRequest(request_id="r", question="q", context=["  "], timeout_seconds=5)
    with pytest.raises(ValidationError):
        AdapterRequest(request_id="r", question="q", timeout_seconds=301)


def test_adapter_contract_rejects_extra_fields_and_invalid_capability() -> None:
    with pytest.raises(ValidationError):
        AdapterCapability(capability_version="adapter-v2", adapter_version="1", trace_level="full")
    with pytest.raises(ValidationError):
        AdapterResponse(
            request_id="r",
            answer="a",
            usage={"latency_ms": 1},
            unexpected="secret",
        )
