"""Judge provider protocol: pluggable, deterministic verdicts, never golden truth.

The judge answers a *bounded* question — is the generated answer correct w.r.t. the
reference answer and gold evidence? It returns a probabilistic verdict plus a
confidence score. A verdict is NEVER golden truth: below the configured confidence
threshold the platform routes the item back to human review (needs_review) instead of
acting on the label.

Implementations are swappable (jev / openai-judge / rule-based / noop) via the
`JudgeProvider` protocol. The default is `noop`, which always reports
`JudgeLabel.unavailable` and keeps the platform deterministic and cost-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

MAX_QUESTION_CHARS = 8_000
MAX_ANSWER_CHARS = 16_000
MAX_REFERENCE_CHARS = 16_000
MAX_EVIDENCE_ITEMS = 20


class JudgeLabel(str, Enum):
    correct = "correct"
    incorrect = "incorrect"
    unavailable = "unavailable"


class JudgeUnavailableError(RuntimeError):
    """The configured judge could not produce a verdict safely."""


@dataclass(frozen=True, slots=True)
class JudgeRequest:
    """Tenant-agnostic judging input; secrets and PII must be stripped upstream."""

    question: str
    answer: str
    reference_answer: str | None = None
    gold_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("judge question must be non-empty")
        if not self.answer.strip():
            raise ValueError("judge answer must be non-empty")
        if len(self.question) > MAX_QUESTION_CHARS:
            raise ValueError("judge question exceeds the configured limit")
        if len(self.answer) > MAX_ANSWER_CHARS:
            raise ValueError("judge answer exceeds the configured limit")
        if self.reference_answer is not None and len(self.reference_answer) > MAX_REFERENCE_CHARS:
            raise ValueError("judge reference answer exceeds the configured limit")
        object.__setattr__(self, "gold_evidence", tuple(self.gold_evidence[:MAX_EVIDENCE_ITEMS]))


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """A probabilistic judgement; confidence is in [0, 1]."""

    label: JudgeLabel
    confidence: float
    judge_name: str
    judge_version: str
    latency_ms: int = 0
    needs_review: bool = False
    provenance: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("judge confidence must be a probability in [0, 1]")
        if not self.judge_name.strip() or not self.judge_version.strip():
            raise ValueError("judge identity must be non-empty")

    @classmethod
    def unavailable(cls, *, judge_name: str, judge_version: str) -> JudgeVerdict:
        return cls(
            label=JudgeLabel.unavailable,
            confidence=0.0,
            judge_name=judge_name,
            judge_version=judge_version,
        )


class JudgeProvider(Protocol):
    """Pluggable judging capability. Implementations must be side-effect free."""

    name: str
    version: str

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        """Return a verdict for one item, or raise JudgeUnavailableError."""
        ...
