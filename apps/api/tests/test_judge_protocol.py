"""Pluggable JudgeProvider protocol and verdict value object."""

from __future__ import annotations

import pytest

from rag_eval_api.judges.protocol import (
    JudgeLabel,
    JudgeRequest,
    JudgeVerdict,
)


def test_judge_request_is_bounded_and_tenant_agnostic() -> None:
    request = JudgeRequest(
        question="什么是 RAG？",
        answer="RAG 是检索增强生成。",
        reference_answer="检索增强生成（RAG）结合检索与生成。",
        gold_evidence=["检索增强生成的定义"],
    )
    assert request.question
    assert request.reference_answer is not None


def test_judge_verdict_requires_label_and_confidence_bounded() -> None:
    verdict = JudgeVerdict(
        label=JudgeLabel.correct,
        confidence=0.9,
        judge_name="jev",
        judge_version="judge-v1",
        latency_ms=12,
    )
    assert verdict.label is JudgeLabel.correct
    assert 0.0 <= verdict.confidence <= 1.0


def test_confidence_must_be_probability() -> None:
    with pytest.raises(ValueError):
        JudgeVerdict(
            label=JudgeLabel.incorrect,
            confidence=1.5,
            judge_name="jev",
            judge_version="judge-v1",
        )


def test_low_confidence_verdict_marks_needs_review() -> None:
    verdict = JudgeVerdict(
        label=JudgeLabel.correct,
        confidence=0.55,
        judge_name="jev",
        judge_version="judge-v1",
        needs_review=True,
    )
    assert verdict.needs_review is True


def test_noop_verdict_is_explicitly_unavailable() -> None:
    verdict = JudgeVerdict.unavailable(judge_name="noop", judge_version="judge-v1")
    assert verdict.label is JudgeLabel.unavailable
    assert verdict.confidence == 0.0
