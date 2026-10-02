"""Jev judge: TypeSafe System One decision model over HTTP.

Jev is a fast (<50 ms) deterministic decision model exposing a `classify(input,
labels, confidence_threshold)` shape. This client adapts answer-correctness judging
onto that contract. It is fully opt-in (requires an explicit base URL and API key),
sends bounded, secret-stripped input, enforces a timeout, and raises
`JudgeUnavailableError` on any unsafe outcome so the worker can fall back.

Jev is NEVER golden truth. Low-confidence verdicts are marked `needs_review` so a
human confirms them before they affect downstream gates.
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

CORRECT_LABEL = "correct"
INCORRECT_LABEL = "incorrect"
MAX_CLASSIFY_INPUT_CHARS = 32_000


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


def _build_classify_prompt(request: JudgeRequest) -> str:
    parts = [
        "判定下面生成的回答是否与参考答案一致。只输出 correct 或 incorrect。",
        f"问题：{request.question}",
        f"参考答案：{request.reference_answer or ''}",
        f"生成答案：{request.answer}",
    ]
    if request.gold_evidence:
        parts.append("标准证据：" + " | ".join(request.gold_evidence))
    return "\n".join(parts)[:MAX_CLASSIFY_INPUT_CHARS]


def _parse_verdict(
    payload: dict[str, Any],
    *,
    judge_name: str,
    judge_version: str,
    latency_ms: int,
    threshold: float,
) -> JudgeVerdict:
    probabilities = payload.get("probabilities")
    if not isinstance(probabilities, dict):
        raise ValueError("jev classify response is missing probabilities")
    correct_raw = probabilities.get(CORRECT_LABEL)
    if not isinstance(correct_raw, int | float):
        raise ValueError("jev classify response is missing the correct probability")
    confidence = float(correct_raw)
    label = JudgeLabel.correct if confidence >= threshold else JudgeLabel.incorrect
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
    """HTTP client adapting answer-correctness onto Jev's classify contract."""

    name = "jev"
    version = "judge-v1"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        confidence_threshold: float = 0.7,
        timeout_seconds: int = 10,
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
        self._transport = transport or _UrllibTransport()

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        started = time.perf_counter()
        headers: dict[str, str] = {}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        body = {
            "input": _build_classify_prompt(request),
            "labels": [CORRECT_LABEL, INCORRECT_LABEL],
            "confidence_threshold": self._threshold,
        }
        try:
            payload = self._transport.post(
                f"{self._base_url}/classify",
                payload=body,
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
