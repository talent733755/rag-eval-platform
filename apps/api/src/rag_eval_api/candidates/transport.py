"""SSRF-resistant HTTP transport for explicitly configured model providers."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from rag_eval_api.candidates.errors import ProviderSecurityError, ProviderTransportError


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    url: str
    host: str
    port: int


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return [ipaddress.ip_address(result[4][0]) for result in socket.getaddrinfo(host, None)]


def validate_provider_endpoint(
    url: str,
    *,
    app_env: str,
    allowed_hosts: Iterable[str],
    allowed_ports: Iterable[int],
    resolve: Callable[[str], list[ipaddress.IPv4Address | ipaddress.IPv6Address]] = _resolve,
) -> ProviderEndpoint:
    parsed = urlsplit(url)
    if parsed.scheme not in ({"https"} if app_env != "development" else {"http", "https"}):
        raise ProviderSecurityError("provider endpoint must use HTTPS outside development")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ProviderSecurityError("provider endpoint must not contain credentials")
    host = parsed.hostname.lower()
    hosts = {item.lower() for item in allowed_hosts}
    if host not in hosts:
        raise ProviderSecurityError("provider endpoint host is not allowlisted")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ProviderSecurityError("provider endpoint port is invalid") from exc
    if port not in set(allowed_ports):
        raise ProviderSecurityError("provider endpoint port is not allowlisted")
    try:
        addresses = resolve(host)
    except OSError as exc:
        raise ProviderSecurityError("provider endpoint could not be resolved") from exc
    if not addresses or any(
        address.is_private or address.is_loopback or address.is_link_local for address in addresses
    ):
        raise ProviderSecurityError("provider endpoint resolves to a private address")
    return ProviderEndpoint(url=url.rstrip("/"), host=host, port=port)


class ProviderTransport:
    """Bounded JSON client that never follows redirects or exposes secrets."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str,
        app_env: str,
        allowed_hosts: Iterable[str],
        allowed_ports: Iterable[int],
        timeout_seconds: float = 30,
        resolve: Callable[[str], list[ipaddress.IPv4Address | ipaddress.IPv6Address]] = _resolve,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between 0 and 300")
        self.endpoint = validate_provider_endpoint(
            base_url,
            app_env=app_env,
            allowed_hosts=allowed_hosts,
            allowed_ports=allowed_ports,
            resolve=resolve,
        )
        self.api_key = api_key
        self.timeout = httpx.Timeout(timeout_seconds)
        self.http_transport = http_transport

    def post_json(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            with httpx.Client(
                base_url=self.endpoint.url,
                headers={"authorization": f"Bearer {self.api_key}"},
                follow_redirects=False,
                timeout=self.timeout,
                transport=self.http_transport,
            ) as client:
                response = client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTransportError(
                "provider_timeout", "Provider request timed out.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderTransportError(
                "provider_unavailable", "Provider request failed safely.", retryable=True
            ) from exc
        if response.is_redirect:
            raise ProviderTransportError(
                "provider_redirect_disallowed", "Provider redirects are not allowed."
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderTransportError(
                "provider_unavailable", "Provider returned a retryable error.", retryable=True
            )
        if response.status_code >= 400:
            raise ProviderTransportError("provider_rejected", "Provider rejected the request.")
        try:
            value = response.json()
        except ValueError as exc:
            raise ProviderTransportError(
                "invalid_provider_output", "Provider returned invalid JSON."
            ) from exc
        if not isinstance(value, dict):
            raise ProviderTransportError(
                "invalid_provider_output", "Provider returned invalid JSON."
            )
        return value
