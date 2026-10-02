"""Rule-based and noop judge implementations."""

from __future__ import annotations

from rag_eval_api.judges.noop import NoopJudge
from rag_eval_api.judges.protocol import JudgeLabel, JudgeRequest
from rag_eval_api.judges.rule_based import RuleBasedJudge


def _request(answer: str, reference: str | None) -> JudgeRequest:
    return JudgeRequest(question="问题", answer=answer, reference_answer=reference)


def test_noop_judge_is_always_unavailable() -> None:
    judge = NoopJudge()
    verdict = judge.judge(_request("答案", "参考"))
    assert verdict.label is JudgeLabel.unavailable
    assert verdict.judge_name == "noop"


def test_rule_based_exact_match_is_correct_with_high_confidence() -> None:
    judge = RuleBasedJudge()
    verdict = judge.judge(_request("检索增强生成", "检索增强生成"))
    assert verdict.label is JudgeLabel.correct
    assert verdict.confidence == 1.0
    assert verdict.needs_review is False


def test_rule_based_no_overlap_is_incorrect() -> None:
    judge = RuleBasedJudge()
    verdict = judge.judge(_request("完全无关的回答", "检索增强生成结合检索与生成"))
    assert verdict.label is JudgeLabel.incorrect
    assert verdict.confidence > 0.0


def test_rule_based_missing_reference_is_unavailable() -> None:
    judge = RuleBasedJudge()
    verdict = judge.judge(_request("答案", None))
    assert verdict.label is JudgeLabel.unavailable
    assert verdict.needs_review is False


def test_rule_based_partial_overlap_is_low_confidence_and_reviewed() -> None:
    judge = RuleBasedJudge(low_confidence_threshold=0.8)
    # Shares some tokens but is not an exact match.
    verdict = judge.judge(_request("检索增强生成是一种技术", "检索增强生成结合检索与生成"))
    assert verdict.label is not JudgeLabel.unavailable
    assert verdict.confidence < 0.8
    assert verdict.needs_review is True
