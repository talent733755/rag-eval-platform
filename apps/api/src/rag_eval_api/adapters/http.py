"""Secure HTTP implementation of the adapter-v1 contract."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from ipaddress import IPv4Address, IPv6Address

import httpx

from rag_eval_api.adapters.errors import AdapterError, AdapterUnavailableError
from rag_eval_api.adapters.protocol import (
    ADAPTER_CAPABILITY_VERSION,
    AdapterCapability,
    AdapterRequest,
    AdapterResponse,
)
from rag_eval_api.candidates.transport import validate_provider_endpoint

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class HttpAdapter:
    """Call a JSON HTTP endpoint without allowing network policy bypasses."""

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str | None,
        adapter_version: str,
        trace_level: str,
        app_env: str,
        allowed_hosts: Iterable[str],
        allowed_ports: Iterable[int],
        timeout_seconds: float = 30,
        resolve: Callable[[str], list[IPv4Address | IPv6Address]] | None = None,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        endpoint_kwargs: dict[str, object] = {
            "url": base_url,
            "app_env": app_env,
            "allowed_hosts": allowed_hosts,
            "allowed_ports": allowed_ports,
        }
        if resolve is not None:
            endpoint_kwargs["resolve"] = resolve
        self.endpoint = validate_provider_endpoint(**endpoint_kwargs)  # type: ignore[arg-type]
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between 0 and 300")
        self.timeout = httpx.Timeout(timeout_seconds)
        self.bearer_token = bearer_token
        self.http_transport = http_transport
        self.capability = AdapterCapability(
            capability_version=ADAPTER_CAPABILITY_VERSION,
            adapter_version=adapter_version,
            trace_level=trace_level,
        )

    def run(self, request: AdapterRequest) -> AdapterResponse:
        headers = {"accept": "application/json", "content-type": "application/json"}
        if self.bearer_token:
            headers["authorization"] = f"Bearer {self.bearer_token}"
        try:
            with httpx.Client(
                base_url=self.endpoint.url,
                headers=headers,
                follow_redirects=False,
                timeout=self.timeout,
                transport=self.http_transport,
            ) as client:
                response = client.post("/invoke", json=request.model_dump(mode="json"))
        except httpx.TimeoutException as exc:
            raise AdapterUnavailableError(
                "adapter_timeout", "Adapter request timed out.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise AdapterUnavailableError(
                "adapter_unavailable", "Adapter request failed safely.", retryable=True
            ) from exc
        if response.is_redirect:
            raise AdapterError("adapter_redirect_disallowed", "Adapter redirects are not allowed.")
        if response.status_code == 429 or response.status_code >= 500:
            raise AdapterUnavailableError(
                "adapter_unavailable", "Adapter returned a retryable error.", retryable=True
            )
        if response.status_code >= 400:
            raise AdapterError("adapter_rejected", "Adapter rejected the request.")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise AdapterError(
                "adapter_response_too_large", "Adapter response exceeded the configured limit."
            )
        try:
            result = AdapterResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise AdapterError(
                "invalid_adapter_response", "Adapter response did not match adapter-v1."
            ) from exc
        if result.request_id != request.request_id:
            raise AdapterError(
                "adapter_request_id_mismatch", "Adapter response request ID did not match."
            )
        return result
