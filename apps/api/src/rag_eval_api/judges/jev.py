"""Jev judge: TypeSafe System One decision model over its real ``/systemone`` contract.

Jev exposes ``POST {base_url}/systemone`` with a body of ``{model, state, questions}``.
Each question is a typed object; for answer-correctness judging we use a single
``choice`` question with the two options ``correct`` / ``incorrect`` and a matching
``criteria`` map. Jev answers each question with ``{choice, confidence, probabilities}``.

The verdict is NEVER golden truth: a low confidence marks the verdict ``needs_review``
so a human confirms it before it affects downstream gates. The client is fully opt-in
(requires an explicit base URL), sends bounded secret-stripped input, enforces a
timeout, and raises ``JudgeUnavailableError`` on any unsafe outcome so the worker can
fall back to a missing metric rather than fabricating a label.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Protocol

from rag_eval_api.judges.protocol import (
    JudgeLabel,
    JudgeRequest,
    JudgeUnavailableError,
    JudgeVerdict,
)

CORRECT_OPTION = "correct"
INCORRECT_OPTION = "incorrect"
QUESTION_KEY = "answer_correctness"
MAX_STATE_CHARS = 32_000
DEFAULT_JEV_MODEL = "jev-latest"


class _Transport(Protocol):
    def post(
        self, url: str, *, payload: dict[str, Any], headers: dict[str, str], timeout: int
    ) -> dict[str, Any]: ...


class _UrllibTransport:
    """Minimal stdlib POST client so the judge has no third-party dependency."""

    def post(
        self, url: str, *, payload: dict[str, Any], headers: dict[str, str], timeout: int
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"content-type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read()
        result: dict[str, Any] = json.loads(body.decode())
        return result


def _build_state(request: JudgeRequest) -> str:
    """Build the bounded ``state`` context string from the judging inputs."""

    parts = [
        f"问题：{request.question}",
        f"参考答案：{request.reference_answer or ''}",
        f"生成答案：{request.answer}",
    ]
    if request.gold_evidence:
        parts.append("标准证据：" + " | ".join(request.gold_evidence))
    return "\n".join(parts)[:MAX_STATE_CHARS]


def _build_payload(request: JudgeRequest, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "state": _build_state(request),
        "questions": {
            QUESTION_KEY: {
                "type": "choice",
                "question": "生成答案与参考答案是否语义一致（正确回答了问题）",
                "options": {
                    CORRECT_OPTION: "一致：生成答案在语义上等价于参考答案，正确回答了问题",
                    INCORRECT_OPTION: "不一致：生成答案与参考答案矛盾、缺失关键信息或答非所问",
                },
                "criteria": {
                    CORRECT_OPTION: "生成答案与参考答案语义等价，且正确回答了问题",
                    INCORRECT_OPTION: "生成答案与参考答案矛盾、缺失关键信息或答非所问",
                },
            }
        },
    }


def _parse_verdict(
    payload: dict[str, Any],
    *,
    judge_name: str,
    judge_version: str,
    latency_ms: int,
    threshold: float,
) -> JudgeVerdict:
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("jev systemone response is missing answers")
    answer = answers.get(QUESTION_KEY)
    if not isinstance(answer, dict):
        raise ValueError("jev systemone response is missing the correctness answer")
    choice = answer.get("choice")
    confidence_raw = answer.get("confidence")
    if not isinstance(choice, str) or choice not in (CORRECT_OPTION, INCORRECT_OPTION):
        raise ValueError("jev systemone response has an unexpected choice")
    if not isinstance(confidence_raw, int | float):
        raise ValueError("jev systemone response is missing confidence")
    confidence = float(confidence_raw)
    label = JudgeLabel.correct if choice == CORRECT_OPTION else JudgeLabel.incorrect
    return JudgeVerdict(
        label=label,
        confidence=round(min(1.0, max(0.0, confidence)), 4),
        judge_name=judge_name,
        judge_version=judge_version,
        latency_ms=latency_ms,
        needs_review=confidence < threshold,
        provenance={"threshold": f"{threshold:.2f}"},
    )


class JevJudge:
    """HTTP client adapting answer-correctness onto Jev's real /systemone contract."""

    name = "jev"
    version = "judge-v1"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        confidence_threshold: float = 0.7,
        timeout_seconds: int = 10,
        model: str = DEFAULT_JEV_MODEL,
        transport: _Transport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("jev judge requires an explicit base_url")
        if not 0.0 < confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in (0, 1]")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._threshold = confidence_threshold
        self._timeout = timeout_seconds
        self._model = model
        self._transport = transport or _UrllibTransport()

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        started = time.perf_counter()
        headers: dict[str, str] = {}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        try:
            payload = self._transport.post(
                f"{self._base_url}/systemone",
                payload=_build_payload(request, self._model),
                headers=headers,
                timeout=self._timeout,
            )
        except Exception as exc:  # network/timeout/HTTP failures are all unsafe
            raise JudgeUnavailableError(f"jev judge request failed: {type(exc).__name__}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            return _parse_verdict(
                payload,
                judge_name=self.name,
                judge_version=self.version,
                latency_ms=latency_ms,
                threshold=self._threshold,
            )
        except ValueError as exc:
            raise JudgeUnavailableError(f"jev judge response invalid: {exc}") from exc
