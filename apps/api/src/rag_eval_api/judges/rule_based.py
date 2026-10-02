"""Deterministic rule-based judge: exact-match / token-overlap heuristics.

This is the offline reference judge. It never calls an external service, so it is
reproducible and free. Its confidence is derived from token overlap, which makes it a
baseline for answer correctness — not a substitute for human review. Below the
configured confidence threshold it marks the verdict `needs_review`.
"""

from __future__ import annotations

import re
import time

from rag_eval_api.judges.protocol import JudgeLabel, JudgeRequest, JudgeVerdict

_CJK = re.compile(r"[\u3400-\u9fff]")
_WORD = re.compile(r"[0-9a-z]+")


class RuleBasedJudge:
    """Lexical-similarity judge with a configurable review threshold."""

    name = "rule-based"
    version = "judge-v1"

    def __init__(self, *, low_confidence_threshold: float = 0.8) -> None:
        if not 0.0 < low_confidence_threshold <= 1.0:
            raise ValueError("low_confidence_threshold must be in (0, 1]")
        self._threshold = low_confidence_threshold

    @staticmethod
    def _tokens(text: str) -> set[str]:
        lowered = text.lower()
        tokens = set(_WORD.findall(lowered))
        tokens.update(_CJK.findall(lowered))
        return tokens

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        started = time.perf_counter()
        reference = (request.reference_answer or "").strip()
        if not reference:
            return JudgeVerdict.unavailable(judge_name=self.name, judge_version=self.version)

        answer = request.answer.strip()
        if answer.lower() == reference.lower():
            return JudgeVerdict(
                label=JudgeLabel.correct,
                confidence=1.0,
                judge_name=self.name,
                judge_version=self.version,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        answer_tokens = self._tokens(answer)
        reference_tokens = self._tokens(reference)
        if not reference_tokens:
            return JudgeVerdict.unavailable(judge_name=self.name, judge_version=self.version)
        overlap = len(answer_tokens & reference_tokens) / len(reference_tokens)

        if overlap == 0.0:
            return JudgeVerdict(
                label=JudgeLabel.incorrect,
                confidence=1.0,
                judge_name=self.name,
                judge_version=self.version,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        # Partial overlap: scale confidence so weak matches route to human review.
        confidence = round(min(1.0, overlap), 4)
        label = JudgeLabel.correct if overlap >= self._threshold else JudgeLabel.incorrect
        return JudgeVerdict(
            label=label,
            confidence=confidence,
            judge_name=self.name,
            judge_version=self.version,
            latency_ms=int((time.perf_counter() - started) * 1000),
            needs_review=confidence < self._threshold,
        )
