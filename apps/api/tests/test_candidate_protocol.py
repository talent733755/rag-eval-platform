from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from rag_eval_api.candidates.fake import FakeCandidateGenerator
from rag_eval_api.candidates.protocol import (
    CandidateGenerationRequest,
    CandidateGenerator,
    CandidateItemDraft,
    GenerationFailure,
)


def _request() -> CandidateGenerationRequest:
    return CandidateGenerationRequest(
        document_version_id=uuid4(),
        dataset_name="test-dataset",
        capability_version="candidate-generation-v1",
        parser_version="parser-v1",
        prompt_version="prompt-v1",
        check_rules_version="checks-v1",
        seed=7,
        randomness=0.0,
        chunks=(
            {
                "chunk_id": str(uuid4()),
                "ordinal": 0,
                "content": "A source paragraph.",
                "content_hash": "a" * 64,
                "source_location": {"paragraph": 1},
            },
        ),
        request_id="request-1",
    )


def test_candidate_generator_is_a_versioned_public_protocol() -> None:
    assert CandidateGenerator.__name__ == "CandidateGenerator"
    request = _request()
    result = FakeCandidateGenerator().generate(request)
    assert result.capability_version == "candidate-generation-v1"
    assert result.provider_name == "fake-test"
    assert result.items[0].evidence[0].source_version_id == request.document_version_id


def test_fake_generation_is_deterministic_for_the_same_snapshot() -> None:
    request = _request()
    first = FakeCandidateGenerator().generate(request).model_dump_json()
    second = FakeCandidateGenerator().generate(request).model_dump_json()
    assert first == second


def test_candidate_request_rejects_unknown_capability_and_invalid_hash() -> None:
    with pytest.raises(ValidationError):
        CandidateGenerationRequest(
            **_request().model_dump(exclude={"capability_version"}),
            capability_version="unknown",
        )
    with pytest.raises(ValidationError):
        CandidateGenerationRequest(
            **_request().model_dump(exclude={"chunks"}),
            chunks=(
                {
                    "chunk_id": str(uuid4()),
                    "ordinal": 0,
                    "content": "source",
                    "content_hash": "not-a-hash",
                    "source_location": {},
                },
            ),
        )


def test_generation_result_rejects_evidence_from_another_version() -> None:
    with pytest.raises(ValidationError):
        CandidateItemDraft(
            question="What?",
            source_version_id=uuid4(),
            question_type="factual",
            reference_answer="Answer",
            confidence=0.9,
            automatic_checks={},
            evidence=[
                {
                    "source_version_id": uuid4(),
                    "chunk_id": uuid4(),
                    "ordinal": 0,
                    "excerpt": "source",
                }
            ],
            provenance={},
        )


def test_generation_failure_exposes_stable_retryable_error() -> None:
    failure = GenerationFailure(code="provider_not_configured", retryable=False)
    assert failure.safe_message
