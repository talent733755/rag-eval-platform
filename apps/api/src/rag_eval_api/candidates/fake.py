"""Deterministic test-only candidate provider."""

from __future__ import annotations

import hashlib

from rag_eval_api.candidates.protocol import (
    CandidateEvidence,
    CandidateGenerationRequest,
    CandidateGenerationResult,
    CandidateItemDraft,
)


class FakeCandidateGenerator:
    """Generate deterministic fixtures; never selected by production config."""

    def generate(
        self,
        request: CandidateGenerationRequest,
        cancel_token: object | None = None,
    ) -> CandidateGenerationResult:
        del cancel_token
        selected = min(
            request.chunks,
            key=lambda chunk: hashlib.sha256(
                f"{request.seed}:{chunk.ordinal}:{chunk.content_hash}".encode()
            ).hexdigest(),
        )
        item = CandidateItemDraft(
            source_version_id=request.document_version_id,
            question=f"What is described in paragraph {selected.ordinal}?",
            question_type="factual",
            reference_answer=selected.content,
            confidence=1.0,
            automatic_checks={"deterministic_fixture": True},
            evidence=(
                CandidateEvidence(
                    source_version_id=request.document_version_id,
                    chunk_id=selected.chunk_id,
                    ordinal=selected.ordinal,
                    excerpt=selected.content[:10_000],
                ),
            ),
            provenance={
                "provider": "fake-test",
                "request_id": request.request_id,
                "chunk_content_hash": selected.content_hash,
            },
        )
        return CandidateGenerationResult(
            capability_version=request.capability_version,
            provider_name="fake-test",
            items=(item,),
            provenance={
                "request_id": request.request_id,
                "document_version_id": str(request.document_version_id),
                "chunk_content_hashes": [chunk.content_hash for chunk in request.chunks],
            },
        )
