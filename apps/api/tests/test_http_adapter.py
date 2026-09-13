from ipaddress import ip_address

import httpx
import pytest

from rag_eval_api.adapters.errors import AdapterError, AdapterUnavailableError
from rag_eval_api.adapters.http import HttpAdapter
from rag_eval_api.adapters.protocol import AdapterRequest


def make_adapter(handler):
    return HttpAdapter(
        "https://adapter.example.test",
        bearer_token="do-not-log",
        adapter_version="1.0.0",
        trace_level="minimal",
        app_env="production",
        allowed_hosts=["adapter.example.test"],
        allowed_ports=[443],
        resolve=lambda host: [ip_address("93.184.216.34")],
        http_transport=httpx.MockTransport(handler),
    )


def request() -> AdapterRequest:
    return AdapterRequest(request_id="request-1", question="问题", timeout_seconds=5)


def test_http_adapter_validates_response_and_forwards_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/invoke"
        assert request.headers["authorization"] == "Bearer do-not-log"
        return httpx.Response(
            200,
            json={
                "request_id": "request-1",
                "answer": "答案",
                "usage": {"latency_ms": 12},
            },
        )

    response = make_adapter(handler).run(request())

    assert response.answer == "答案"


def test_http_adapter_classifies_retryable_status_without_leaking_body() -> None:
    adapter = make_adapter(lambda _: httpx.Response(503, text="secret internal response"))

    with pytest.raises(AdapterUnavailableError, match="retryable") as error:
        adapter.run(request())

    assert error.value.code == "adapter_unavailable"
    assert "secret" not in str(error.value)
    assert error.value.retryable is True


def test_http_adapter_rejects_response_request_id_mismatch() -> None:
    adapter = make_adapter(
        lambda _: httpx.Response(
            200,
            json={"request_id": "other", "answer": "答案", "usage": {"latency_ms": 1}},
        )
    )

    with pytest.raises(AdapterError) as error:
        adapter.run(request())

    assert error.value.code == "adapter_request_id_mismatch"
