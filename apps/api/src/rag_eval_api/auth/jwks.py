"""JWKS fetching with bounded caching for OIDC verification.

The fetcher is a thin, injectable HTTP client that downloads the provider's JWKS
document and caches it for a bounded TTL so token verification does not hit the
identity provider on every request. It has no cryptographic logic — that lives in
:mod:`rag_eval_api.auth.oidc`.

Red lines:

* **HTTPS only, caller-validated.** The URL scheme is validated by settings before a
  fetcher is constructed; this module does not silently upgrade `http`.
* **Bounded cache and timeout.** A configurable TTL and a short request timeout keep a
  slow or compromised JWKS endpoint from stalling request handling.
* **Fail closed.** A fetch or parse failure raises :class:`InvalidTokenError` so
  verification fails rather than trusting stale or malformed keys.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from rag_eval_api.auth.jwt import InvalidTokenError

_TIMEOUT_SECONDS = 5.0


class HttpJwksFetcher:
    """Fetch and cache a JWKS document over HTTPS."""

    def __init__(
        self,
        jwks_url: str,
        *,
        cache_seconds: int = 300,
        client: httpx.Client | None = None,
    ) -> None:
        if not jwks_url.startswith("https://"):
            raise ValueError("JWKS URL must use https")
        self._url = jwks_url
        self._cache_seconds = cache_seconds
        self._client = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
        self._keys: list[dict[str, Any]] | None = None
        self._fetched_at = 0.0

    def fetch(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._keys is not None and (now - self._fetched_at) < self._cache_seconds:
            return list(self._keys)
        try:
            response = self._client.get(self._url)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InvalidTokenError("JWKS could not be fetched") from exc
        keys = document.get("keys") if isinstance(document, dict) else None
        if not isinstance(keys, list) or not all(isinstance(key, dict) for key in keys):
            raise InvalidTokenError("JWKS document is malformed")
        self._keys = keys
        self._fetched_at = now
        return list(keys)
