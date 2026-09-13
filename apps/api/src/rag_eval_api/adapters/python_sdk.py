"""Process-isolated Python entry point adapter for the adapter-v1 contract."""

from __future__ import annotations

import json
import multiprocessing
from collections.abc import Callable
from typing import Any

from rag_eval_api.adapters.errors import AdapterError, AdapterUnavailableError
from rag_eval_api.adapters.protocol import (
    ADAPTER_CAPABILITY_VERSION,
    AdapterCapability,
    AdapterRequest,
    AdapterResponse,
)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PythonEntryPoint = Callable[[dict[str, object]], AdapterResponse | dict[str, object]]


def _invoke(entrypoint: PythonEntryPoint, request: dict[str, object], connection: Any) -> None:
    try:
        result = entrypoint(request)
        payload = result.model_dump(mode="json") if isinstance(result, AdapterResponse) else result
        if not isinstance(payload, dict):
            raise TypeError("entrypoint must return an object")
        connection.send_bytes(json.dumps(payload, ensure_ascii=False).encode())
    except Exception:
        connection.send_bytes(b'{"__error__":"invalid_adapter_response"}')
    finally:
        connection.close()


class PythonSdkAdapter:
    """Load a development/test entry point in a bounded child process.

    Production callers should register a trusted, installed package entry point;
    this adapter never evaluates source strings or user-submitted code.
    """

    def __init__(
        self,
        entrypoint: PythonEntryPoint,
        *,
        adapter_version: str,
        trace_level: str,
        timeout_seconds: float = 30,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        context: Any | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between 0 and 300")
        if max_response_bytes < 1 or max_response_bytes > MAX_RESPONSE_BYTES:
            raise ValueError("max_response_bytes is outside the supported range")
        self.entrypoint = entrypoint
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.context = context or multiprocessing.get_context("spawn")
        self.capability = AdapterCapability(
            capability_version=ADAPTER_CAPABILITY_VERSION,
            adapter_version=adapter_version,
            trace_level=trace_level,
        )

    def run(self, request: AdapterRequest) -> AdapterResponse:
        parent, child = self.context.Pipe(duplex=False)
        process = self.context.Process(
            target=_invoke,
            args=(self.entrypoint, request.model_dump(mode="json"), child),
        )
        process.start()
        child.close()
        try:
            if not parent.poll(self.timeout_seconds):
                raise AdapterUnavailableError(
                    "adapter_timeout", "Adapter request timed out.", retryable=True
                )
            try:
                payload = parent.recv_bytes(self.max_response_bytes)
            except OSError as exc:
                raise AdapterError(
                    "adapter_response_too_large", "Adapter response exceeded the configured limit."
                ) from exc
            if len(payload) > self.max_response_bytes:
                raise AdapterError(
                    "adapter_response_too_large", "Adapter response exceeded the configured limit."
                )
            decoded = json.loads(payload)
            if not isinstance(decoded, dict) or decoded.get("__error__"):
                raise AdapterError(
                    "invalid_adapter_response", "Adapter response did not match adapter-v1."
                )
            try:
                response = AdapterResponse.model_validate(decoded)
            except (TypeError, ValueError) as exc:
                raise AdapterError(
                    "invalid_adapter_response", "Adapter response did not match adapter-v1."
                ) from exc
            if response.request_id != request.request_id:
                raise AdapterError(
                    "adapter_request_id_mismatch", "Adapter response request ID did not match."
                )
            return response
        finally:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
            parent.close()
