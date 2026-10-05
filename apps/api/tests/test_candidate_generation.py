from __future__ import annotations

import ipaddress
import json
from uuid import uuid4

import httpx
import pytest

from rag_eval_api.candidates.protocol import CandidateGenerationRequest
from rag_eval_api.candidates.provider import OpenAICompatibleCandidateGenerator


def test_openai_compatible_provider_validates_structured_candidate_output() -> None:
    version_id = uuid4()
    chunk_id = uuid4()
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "items": [
                                {
                                    "source_version_id": str(version_id),
                                    "question": "What?",
                                    "question_type": "factual",
                                    "reference_answer": "Answer",
                                    "confidence": 0.8,
                                    "automatic_checks": {},
                                    "evidence": [
                                        {
                                            "source_version_id": str(version_id),
                                            "chunk_id": str(chunk_id),
                                            "ordinal": 0,
                                            "excerpt": "source",
                                        }
                                    ],
                                    "provenance": {},
                                }
                            ]
                        }
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    provider = OpenAICompatibleCandidateGenerator(
        base_url="https://llm.example.com/v1",
        api_key="secret",
        model_name="model",
        app_env="production",
        allowed_hosts={"llm.example.com"},
        allowed_ports={443},
        resolve=lambda _: [ipaddress.ip_address("93.184.216.34")],
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    request = CandidateGenerationRequest(
        document_version_id=version_id,
        dataset_name="dataset",
        capability_version="candidate-generation-v1",
        prompt_version="prompt-v1",
        randomness=0,
        request_id="request-1",
        chunks=(
            {
                "chunk_id": chunk_id,
                "ordinal": 0,
                "content": "source",
                "content_hash": "a" * 64,
            },
        ),
    )
    result = provider.generate(request)
    assert result.items[0].question == "What?"
    assert result.usage.input_tokens == 3


def test_openai_compatible_provider_normalizes_common_model_schema_drift() -> None:
    """The gateway model renames keys, invents question types and cites flat chunk ids."""

    version_id = uuid4()
    chunk_id = uuid4()
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "candidates": [
                                {
                                    "question": "What type is this lesson?",
                                    "question_type": "factoid",
                                    "reference_answer": "Image/text.",
                                    "supporting_chunk_ids": [str(chunk_id)],
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
    provider = OpenAICompatibleCandidateGenerator(
        base_url="https://llm.example.com/v1",
        api_key="secret",
        model_name="model",
        app_env="production",
        allowed_hosts={"llm.example.com"},
        allowed_ports={443},
        resolve=lambda _: [ipaddress.ip_address("93.184.216.34")],
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    request = CandidateGenerationRequest(
        document_version_id=version_id,
        dataset_name="dataset",
        capability_version="candidate-generation-v1",
        prompt_version="prompt-v1",
        randomness=0,
        request_id="request-1",
        chunks=(
            {
                "chunk_id": chunk_id,
                "ordinal": 3,
                "content": "lesson body",
                "content_hash": "a" * 64,
            },
        ),
    )
    result = provider.generate(request)
    assert result.items[0].question_type == "factual"
    assert result.items[0].source_version_id == version_id
    assert result.items[0].evidence[0].ordinal == 3
    assert result.items[0].evidence[0].excerpt == "lesson body"


def test_openai_compatible_provider_drops_items_without_valid_evidence() -> None:
    """An item whose supporting ids do not resolve to real chunks is dropped, not invented."""

    version_id = uuid4()
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "candidates": [
                                {
                                    "question": "Q",
                                    "question_type": "factoid",
                                    "reference_answer": "A",
                                    "supporting_chunk_ids": [str(uuid4())],  # not in request
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
    provider = OpenAICompatibleCandidateGenerator(
        base_url="https://llm.example.com/v1",
        api_key="secret",
        model_name="model",
        app_env="production",
        allowed_hosts={"llm.example.com"},
        allowed_ports={443},
        resolve=lambda _: [ipaddress.ip_address("93.184.216.34")],
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    request = CandidateGenerationRequest(
        document_version_id=version_id,
        dataset_name="dataset",
        capability_version="candidate-generation-v1",
        prompt_version="prompt-v1",
        randomness=0,
        request_id="request-1",
        chunks=(
            {
                "chunk_id": uuid4(),
                "ordinal": 0,
                "content": "source",
                "content_hash": "a" * 64,
            },
        ),
    )
    with pytest.raises(ValueError, match="invalid_provider_output"):
        provider.generate(request)


def test_openai_compatible_provider_rejects_malformed_response() -> None:
    provider = OpenAICompatibleCandidateGenerator(
        base_url="https://llm.example.com/v1",
        api_key="secret",
        model_name="model",
        app_env="production",
        allowed_hosts={"llm.example.com"},
        allowed_ports={443},
        resolve=lambda _: [ipaddress.ip_address("93.184.216.34")],
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": []})),
    )
    with pytest.raises(ValueError, match="invalid_provider_output"):
        provider.generate(
            CandidateGenerationRequest(
                document_version_id=uuid4(),
                dataset_name="dataset",
                capability_version="candidate-generation-v1",
                prompt_version="prompt-v1",
                randomness=0,
                request_id="request-1",
                chunks=(
                    {
                        "chunk_id": uuid4(),
                        "ordinal": 0,
                        "content": "source",
                        "content_hash": "a" * 64,
                    },
                ),
            )
        )
