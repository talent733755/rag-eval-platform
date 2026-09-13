"""OpenAI-compatible candidate provider with strict local validation."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import cast

import httpx

from rag_eval_api.candidates.errors import ProviderTransportError
from rag_eval_api.candidates.protocol import (
    CandidateGenerationRequest,
    CandidateGenerationResult,
    CandidateItemDraft,
    UsageSnapshot,
)
from rag_eval_api.candidates.transport import ProviderTransport


class OpenAICompatibleCandidateGenerator:
    """Call the minimal chat-completions shape and validate every result item."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str,
        model_name: str,
        app_env: str,
        allowed_hosts: Iterable[str],
        allowed_ports: Iterable[int],
        timeout_seconds: float = 30,
        resolve: Callable[..., object] | None = None,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        transport_kwargs: dict[str, object] = {
            "base_url": base_url,
            "api_key": api_key,
            "app_env": app_env,
            "allowed_hosts": allowed_hosts,
            "allowed_ports": allowed_ports,
            "timeout_seconds": timeout_seconds,
            "http_transport": http_transport,
        }
        if resolve is not None:
            transport_kwargs["resolve"] = resolve
        self.transport = ProviderTransport(**transport_kwargs)  # type: ignore[arg-type]
        self.model_name = model_name

    def generate(
        self,
        request: CandidateGenerationRequest,
        cancel_token: object | None = None,
    ) -> CandidateGenerationResult:
        del cancel_token
        payload = {
            "model": self.model_name,
            "temperature": request.randomness,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                }
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = self.transport.post_json(payload)
            choices = response.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("missing choices")
            message = choices[0]
            content = (
                message.get("message", {}).get("content") if isinstance(message, dict) else None
            )
            if not isinstance(content, str):
                raise ValueError("missing message content")
            decoded = json.loads(content)
            if not isinstance(decoded, dict):
                raise ValueError("candidate payload must be an object")
            items = tuple(CandidateItemDraft.model_validate(item) for item in decoded["items"])
            usage = response.get("usage", {})
            usage = usage if isinstance(usage, dict) else {}
            return CandidateGenerationResult(
                capability_version=request.capability_version,
                provider_name="openai-compatible",
                items=items,
                usage=UsageSnapshot(
                    input_tokens=cast(int, usage.get("prompt_tokens", 0)),
                    output_tokens=cast(int, usage.get("completion_tokens", 0)),
                ),
                provenance={
                    "request_id": request.request_id,
                    "model_name": self.model_name,
                    "document_version_id": str(request.document_version_id),
                },
            )
        except ProviderTransportError as exc:
            raise ValueError(exc.code) from exc
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_provider_output") from exc
