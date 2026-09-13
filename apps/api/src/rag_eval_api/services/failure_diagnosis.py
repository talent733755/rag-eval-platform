"""Deterministic, explainable failure classification for evaluation items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FailureCode = Literal[
    "adapter_error",
    "retrieval_miss",
    "citation_error",
    "answer_incorrect",
    "timeout",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class FailureClassification:
    code: FailureCode
    retryable: bool
    safe_message: str


def classify_failure(
    *,
    adapter_error: bool = False,
    timed_out: bool = False,
    relevant_retrieved: bool | None = None,
    citations_valid: bool | None = None,
    answer_correct: bool | None = None,
) -> FailureClassification | None:
    """Apply stable precedence so one sample has one primary diagnosis."""

    if not any(
        (
            adapter_error,
            timed_out,
            relevant_retrieved is False,
            citations_valid is False,
            answer_correct is False,
        )
    ):
        return None
    if timed_out:
        return FailureClassification("timeout", True, "评测请求超时。")
    if adapter_error:
        return FailureClassification("adapter_error", True, "Pipeline 返回了不可用响应。")
    if relevant_retrieved is False:
        return FailureClassification("retrieval_miss", False, "标准证据未被召回。")
    if citations_valid is False:
        return FailureClassification("citation_error", False, "回答引用与证据不一致。")
    if answer_correct is False:
        return FailureClassification("answer_incorrect", False, "回答与标准答案不一致。")
    return FailureClassification("unknown", False, "评测失败原因需要进一步分析。")
