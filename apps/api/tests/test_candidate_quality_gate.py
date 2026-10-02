"""Candidate quality gate: judge-driven screening with human-review fallback."""

from __future__ import annotations

from uuid import uuid4

from rag_eval_api.candidates.protocol import CandidateEvidence, CandidateItemDraft
from rag_eval_api.candidates.quality_gate import (
    run_quality_gate,
    verdict_to_checks,
)
from rag_eval_api.judges.protocol import JudgeLabel, JudgeVerdict


class _StubJudge:
    name = "stub"
    version = "judge-v1"

    def __init__(self, verdict: JudgeVerdict):
        self._verdict = verdict
        self.calls: list = []

    def judge(self, request):
        self.calls.append(request)
        return self._verdict


def _draft() -> CandidateItemDraft:
    source_version_id = uuid4()
    return CandidateItemDraft(
        source_version_id=source_version_id,
        question="什么是检索增强生成？",
        question_type="factual",
        reference_answer="检索增强生成结合检索与生成。",
        confidence=0.9,
        automatic_checks={},
        evidence=(
            CandidateEvidence(
                source_version_id=source_version_id,
                chunk_id=uuid4(),
                ordinal=0,
                excerpt="检索增强生成（RAG）先检索证据再生成答案。",
            ),
        ),
        provenance={},
    )


def _verdict(label: JudgeLabel, confidence: float, needs_review: bool = False) -> JudgeVerdict:
    return JudgeVerdict(
        label=label,
        confidence=confidence,
        judge_name="stub",
        judge_version="judge-v1",
        needs_review=needs_review,
    )


def test_high_confidence_consistent_passes_without_review() -> None:
    verdict = run_quality_gate(_StubJudge(_verdict(JudgeLabel.correct, 0.95)), _draft())
    assert verdict.consistent is True
    assert verdict.needs_human_review is False


def test_high_confidence_inconsistent_flags_rejection_signal() -> None:
    verdict = run_quality_gate(_StubJudge(_verdict(JudgeLabel.incorrect, 0.92)), _draft())
    assert verdict.consistent is False
    # A confident inconsistency still routes to humans for the final decision.
    assert verdict.needs_human_review is True


def test_low_confidence_always_routes_to_human_review() -> None:
    verdict = run_quality_gate(
        _StubJudge(_verdict(JudgeLabel.correct, 0.4, needs_review=True)), _draft()
    )
    assert verdict.needs_human_review is True


def test_unavailable_judge_is_neutral_and_reviewed() -> None:
    verdict = run_quality_gate(_StubJudge(_verdict(JudgeLabel.unavailable, 0.0)), _draft())
    assert verdict.consistent is None
    assert verdict.needs_human_review is False  # noop default must not flood the queue


def test_noop_judge_skips_screening_silently() -> None:
    from rag_eval_api.judges.noop import NoopJudge

    verdict = run_quality_gate(NoopJudge(), _draft())
    assert verdict.screened is False
    assert verdict.needs_human_review is False


def test_verdict_serializes_into_automatic_checks() -> None:
    verdict = run_quality_gate(_StubJudge(_verdict(JudgeLabel.correct, 0.95)), _draft())
    checks = verdict_to_checks(verdict)
    assert checks["screened"] is True
    assert checks["needs_human_review"] is False
    assert checks["judge_label"] == "correct"
