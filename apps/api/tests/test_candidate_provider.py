from __future__ import annotations

import ipaddress

import httpx
import pytest

from rag_eval_api.candidates.errors import ProviderSecurityError, ProviderTransportError
from rag_eval_api.candidates.transport import ProviderTransport, validate_provider_endpoint


def test_provider_endpoint_requires_allowlisted_https_host_and_port() -> None:
    endpoint = validate_provider_endpoint(
        "https://llm.example.com/v1",
        app_env="production",
        allowed_hosts={"llm.example.com"},
        allowed_ports={443},
        resolve=lambda _: [ipaddress.ip_address("93.184.216.34")],
    )
    assert endpoint.host == "llm.example.com"
    assert endpoint.port == 443


@pytest.mark.parametrize(
    "url",
    [
        "http://llm.example.com/v1",
        "https://127.0.0.1/v1",
        "https://llm.example.com:8443/v1",
        "https://other.example.com/v1",
        "https://user:secret@llm.example.com/v1",
    ],
)
def test_provider_endpoint_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ProviderSecurityError):
        validate_provider_endpoint(
            url,
            app_env="production",
            allowed_hosts={"llm.example.com"},
            allowed_ports={443},
            resolve=lambda _: [ipaddress.ip_address("127.0.0.1")],
        )


def test_provider_transport_does_not_follow_redirects_or_leak_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-key"
        return httpx.Response(302, headers={"location": "https://evil.example/v1"})

    transport = ProviderTransport(
        "https://llm.example.com/v1",
        api_key="secret-key",
        app_env="production",
        allowed_hosts={"llm.example.com"},
        allowed_ports={443},
        resolve=lambda _: [ipaddress.ip_address("93.184.216.34")],
        http_transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderTransportError) as error:
        transport.post_json({"model": "test"})
    assert "secret-key" not in str(error.value)
    assert error.value.code == "provider_redirect_disallowed"
