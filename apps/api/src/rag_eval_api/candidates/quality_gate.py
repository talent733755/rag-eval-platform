"""Candidate quality gate: judge-driven screening with human-review fallback.

The gate runs the configured judge over each generated candidate draft to pre-screen
*consistency* between the reference answer and the source evidence. It is an advisory
signal, not an auto-rejector:

* The judge is NEVER golden truth. A confident *inconsistency* does not delete the
  candidate; it flags the item for a human to make the final accept/reject call.
* The default `noop` judge reports every draft as unscreened at zero cost, keeping the
  pipeline deterministic and offline.
* The verdict is folded into the item's `automatic_checks` and surfaced in the review
  queue so humans can prioritize borderline candidates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rag_eval_api.candidates.protocol import CandidateItemDraft
from rag_eval_api.judges.protocol import (
    JudgeLabel,
    JudgeProvider,
    JudgeRequest,
    JudgeUnavailableError,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QualityGateVerdict:
    """Advisory screening outcome for one candidate draft."""

    screened: bool
    consistent: bool | None
    needs_human_review: bool
    judge_label: str | None
    confidence: float | None
    judge_name: str
    judge_version: str


def run_quality_gate(judge: JudgeProvider, draft: CandidateItemDraft) -> QualityGateVerdict:
    """Screen one draft; never raises and never auto-rejects."""

    if judge.name == "noop":
        return QualityGateVerdict(
            screened=False,
            consistent=None,
            needs_human_review=False,
            judge_label=None,
            confidence=None,
            judge_name=judge.name,
            judge_version=judge.version,
        )
    try:
        verdict = judge.judge(
            JudgeRequest(
                question=draft.question,
                answer=draft.reference_answer,
                reference_answer=draft.reference_answer,
                gold_evidence=tuple(item.excerpt for item in draft.evidence),
            )
        )
    except JudgeUnavailableError:
        LOGGER.warning(
            "candidate quality gate judge unavailable",
            extra={"event": "candidate.quality_judge_unavailable", "judge_name": judge.name},
        )
        return QualityGateVerdict(
            screened=False,
            consistent=None,
            needs_human_review=False,
            judge_label=None,
            confidence=None,
            judge_name=judge.name,
            judge_version=judge.version,
        )
    except Exception:
        LOGGER.exception(
            "candidate quality gate judge failed",
            extra={"event": "candidate.quality_judge_failed", "judge_name": judge.name},
        )
        return QualityGateVerdict(
            screened=False,
            consistent=None,
            needs_human_review=False,
            judge_label=None,
            confidence=None,
            judge_name=judge.name,
            judge_version=judge.version,
        )

    if verdict.label is JudgeLabel.unavailable:
        return QualityGateVerdict(
            screened=True,
            consistent=None,
            needs_human_review=False,
            judge_label=verdict.label.value,
            confidence=verdict.confidence,
            judge_name=judge.name,
            judge_version=judge.version,
        )

    consistent = verdict.label is JudgeLabel.correct
    # Confident inconsistency and low confidence both need a human; only a confident
    # consistent verdict is left alone.
    needs_human_review = verdict.needs_review or (consistent is False)
    return QualityGateVerdict(
        screened=True,
        consistent=consistent,
        needs_human_review=needs_human_review,
        judge_label=verdict.label.value,
        confidence=verdict.confidence,
        judge_name=judge.name,
        judge_version=judge.version,
    )


def verdict_to_checks(verdict: QualityGateVerdict) -> dict[str, object]:
    """Serialize the verdict into the candidate's `automatic_checks` blob."""

    checks: dict[str, object] = {
        "screened": verdict.screened,
        "needs_human_review": verdict.needs_human_review,
        "judge_name": verdict.judge_name,
        "judge_version": verdict.judge_version,
    }
    if verdict.consistent is not None:
        checks["consistent"] = verdict.consistent
    if verdict.judge_label is not None:
        checks["judge_label"] = verdict.judge_label
    if verdict.confidence is not None:
        checks["confidence"] = verdict.confidence
    return checks
