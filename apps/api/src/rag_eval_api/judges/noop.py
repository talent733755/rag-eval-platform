"""No-op judge: deterministic, offline, never asserts correctness."""

from __future__ import annotations

from rag_eval_api.judges.protocol import JudgeRequest, JudgeVerdict


class NoopJudge:
    """Default judge. Reports every item as `unavailable` at zero cost."""

    name = "noop"
    version = "judge-v1"

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        del request
        return JudgeVerdict.unavailable(judge_name=self.name, judge_version=self.version)
