"""Unit tests for chunked candidate generation in the generation worker."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from rag_eval_api.candidates.protocol import (
    CandidateChunk,
    CandidateEvidence,
    CandidateGenerationResult,
)
from rag_eval_api.services.candidate_worker import (
    CandidateWorker,
    _Claim,
    _select_same_version_evidence,
)


def _chunk(content: str, ordinal: int) -> CandidateChunk:
    return CandidateChunk(
        chunk_id=uuid4(),
        ordinal=ordinal,
        content=content,
        content_hash=f"{ordinal:064d}",
        source_location={},
    )


def _make_claim(worker: CandidateWorker, chunk_count: int) -> _Claim:
    chunks = tuple(_chunk(f"content {index}", index) for index in range(chunk_count))
    return _Claim(
        job_id=uuid4(),
        organization_id=uuid4(),
        project_id=uuid4(),
        dataset_id=uuid4(),
        dataset_version_id=uuid4(),
        source_version_id=uuid4(),
        dataset_name="dataset",
        config_id=uuid4(),
        capability_version="candidate-generation-v1",
        provider_name="fake-test",
        prompt_version="prompt-v1",
        parser_version="parser-v1",
        seed=None,
        randomness=0.0,
        request_id="req",
        chunks=chunks,
        chunk_version={},
        lease_id=uuid4(),
        attempt_number=1,
        fencing_token=1,
        worker_id="worker",
        started_at=datetime.now(UTC),
    )


class _RecordingGenerator:
    """Records the chunks of every call and emits one candidate per batch."""

    def __init__(self, fail_on_call: set[int] | None = None) -> None:
        self.calls: list[int] = []
        self.seen_ordinals: list[list[int]] = []
        self._fail_on_call = fail_on_call or set()

    def generate(self, request: Any, cancel_token: object | None = None) -> Any:
        call_index = len(self.calls)
        self.calls.append(len(request.chunks))
        self.seen_ordinals.append([c.ordinal for c in request.chunks])
        if call_index in self._fail_on_call:
            raise RuntimeError("provider_timeout")
        return self._fake_result(request.chunks)

    @staticmethod
    def _fake_result(chunks: Any) -> CandidateGenerationResult:
        from rag_eval_api.candidates.fake import FakeCandidateGenerator
        from rag_eval_api.candidates.protocol import CandidateGenerationRequest

        request = CandidateGenerationRequest(
            document_version_id=uuid4(),
            dataset_name="dataset",
            capability_version="candidate-generation-v1",
            parser_version="parser-v1",
            prompt_version="prompt-v1",
            seed=1,
            randomness=0.0,
            chunks=chunks,
            request_id="r",
        )
        return FakeCandidateGenerator().generate(request)


def _worker(generator: Any, chunk_batch_size: int) -> CandidateWorker:
    from rag_eval_api.judges.noop import NoopJudge

    return CandidateWorker(
        session_factory=None,  # type: ignore[arg-type]
        generator=generator,
        worker_id="worker",
        judge_provider=NoopJudge(),
        chunk_batch_size=chunk_batch_size,
    )


@pytest.mark.asyncio
async def test_large_snapshot_is_split_into_bounded_batches() -> None:
    generator = _RecordingGenerator()
    worker = _worker(generator, chunk_batch_size=30)
    claim = _make_claim(worker, chunk_count=95)

    result = await worker._generate_all_batches(claim)

    # 95 chunks at 30 per batch -> calls of 30, 30, 30, 5.
    assert generator.calls == [30, 30, 30, 5]
    assert len(result.items) == 4
    assert result.provenance["batch_count"] == 4
    assert result.provenance["succeeded_batches"] == 4


@pytest.mark.asyncio
async def test_partial_success_skips_failed_batches() -> None:
    generator = _RecordingGenerator(fail_on_call={1})
    worker = _worker(generator, chunk_batch_size=2)
    claim = _make_claim(worker, chunk_count=6)

    result = await worker._generate_all_batches(claim)

    assert generator.calls == [2, 2, 2]
    # One batch failed, two succeeded.
    assert len(result.items) == 2
    assert result.provenance["succeeded_batches"] == 2
    assert result.provenance["batch_count"] == 3


@pytest.mark.asyncio
async def test_all_batches_failing_raises_for_safe_failure() -> None:
    generator = _RecordingGenerator(fail_on_call={0, 1})
    worker = _worker(generator, chunk_batch_size=2)
    claim = _make_claim(worker, chunk_count=4)

    with pytest.raises(RuntimeError):
        await worker._generate_all_batches(claim)


@pytest.mark.asyncio
async def test_duplicate_ordinals_across_documents_are_renumbered_per_batch() -> None:
    """Chunks from several document versions share ordinals (each doc starts at 0).

    The public request contract requires unique ordinals, so the worker must
    renumber them per batch while keeping chunk_id stable for evidence mapping.
    """

    generator = _RecordingGenerator()
    worker = _worker(generator, chunk_batch_size=10)
    # Two documents, each with ordinals 0..4 -> duplicates once merged.
    chunks = tuple(
        _chunk(f"doc{doc} chunk{ordinal}", ordinal) for doc in range(2) for ordinal in range(5)
    )
    base = _make_claim(worker, chunk_count=0)
    claim = replace(base, chunks=chunks)

    result = await worker._generate_all_batches(claim)

    assert generator.calls == [10]
    assert len(result.items) == 1
    # The generator must have received unique, contiguous ordinals.
    seen_ordinals = generator.seen_ordinals[0]
    assert sorted(seen_ordinals) == list(range(10))


def test_select_same_version_evidence_drops_cross_version_and_duplicates() -> None:
    version_a = uuid4()
    version_b = uuid4()
    chunk_a = uuid4()
    chunk_b = uuid4()
    chunk_version = {chunk_a: version_a, chunk_b: version_b}
    evidence = (
        CandidateEvidence(source_version_id=version_a, chunk_id=chunk_a, ordinal=0, excerpt="a"),
        # Same chunk/ordinal twice -> collapsed.
        CandidateEvidence(source_version_id=version_a, chunk_id=chunk_a, ordinal=0, excerpt="a2"),
        # Chunk belongs to a different document version -> dropped.
        CandidateEvidence(source_version_id=version_a, chunk_id=chunk_b, ordinal=1, excerpt="b"),
    )

    kept = _select_same_version_evidence(evidence, chunk_version, version_a)

    assert [e.chunk_id for e in kept] == [chunk_a]
