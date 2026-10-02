"""Build a JudgeProvider from configuration; default-off and fail-safe.

Selecting a judge is explicit and opt-in. An unknown kind degrades to the free,
deterministic `noop` judge rather than crashing the worker — a misconfigured judge
must never take an evaluation run down. The Jev judge additionally requires an
explicit base URL and API key so cost and egress are always a deliberate choice.
"""

from __future__ import annotations

import logging

from rag_eval_api.judges.noop import NoopJudge
from rag_eval_api.judges.protocol import JudgeProvider
from rag_eval_api.judges.rule_based import RuleBasedJudge

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD = 0.7


def build_judge_provider(
    *,
    kind: str = "noop",
    jev_base_url: str | None = None,
    jev_api_key: str | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> JudgeProvider:
    """Resolve the configured judge, falling back to noop on misconfiguration."""

    if kind == "noop":
        return NoopJudge()
    if kind == "rule-based":
        return RuleBasedJudge(low_confidence_threshold=confidence_threshold)
    if kind == "jev":
        from rag_eval_api.judges.jev import JevJudge

        if not jev_base_url:
            raise ValueError("jev judge kind requires jev_base_url")
        return JevJudge(
            base_url=jev_base_url,
            api_key=jev_api_key,
            confidence_threshold=confidence_threshold,
        )
    LOGGER.warning(
        "unknown judge kind configured; falling back to noop",
        extra={"event": "judge.unknown_kind", "judge_kind": kind},
    )
    return NoopJudge()
