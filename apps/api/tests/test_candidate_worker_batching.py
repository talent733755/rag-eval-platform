"""Unit tests for chunked candidate generation in the generation worker."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from rag_eval_api.candidates.protocol import CandidateGenerationResult
from rag_eval_api.services.candidate_worker import CandidateWorker, _Claim


def _chunk(content: str, ordinal: int) -> dict[str, Any]:
    return {
        "chunk_id": str(uuid4()),
        "ordinal": ordinal,
        "content": content,
        "content_hash": f"{ordinal:064d}",
        "source_location": {},
    }


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
        self._fail_on_call = fail_on_call or set()

    def generate(self, request: Any, cancel_token: object | None = None) -> Any:
        call_index = len(self.calls)
        self.calls.append(len(request.chunks))
        if call_index in self._fail_on_call:
            raise RuntimeError("provider_timeout")
        result = self._fake_result(request.chunks)
        return result

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
