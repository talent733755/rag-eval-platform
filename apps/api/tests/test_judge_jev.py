"""Jev judge client: deterministic decision-model classification over HTTP."""

from __future__ import annotations

import pytest

from rag_eval_api.judges.jev import JevJudge, _build_classify_prompt, _parse_verdict
from rag_eval_api.judges.protocol import JudgeLabel, JudgeRequest


def test_build_classify_prompt_is_bounded_and_structured() -> None:
    prompt = _build_classify_prompt(
        JudgeRequest(question="问题", answer="答案", reference_answer="参考")
    )
    assert "答案" in prompt and "参考" in prompt
    assert len(prompt) < 100_000


def test_parse_verdict_maps_probability_to_label() -> None:
    verdict = _parse_verdict(
        {"probabilities": {"correct": 0.93, "incorrect": 0.07}},
        judge_name="jev",
        judge_version="judge-v1",
        latency_ms=8,
        threshold=0.7,
    )
    assert verdict.label is JudgeLabel.correct
    assert verdict.confidence == pytest.approx(0.93)
    assert verdict.needs_review is False


def test_parse_verdict_low_confidence_routes_to_review() -> None:
    verdict = _parse_verdict(
        {"probabilities": {"correct": 0.55, "incorrect": 0.45}},
        judge_name="jev",
        judge_version="judge-v1",
        latency_ms=8,
        threshold=0.7,
    )
    assert verdict.confidence < 0.7
    assert verdict.needs_review is True


def test_parse_verdict_rejects_malformed_payload() -> None:
    with pytest.raises(ValueError):
        _parse_verdict(
            {"unexpected": True},
            judge_name="jev",
            judge_version="judge-v1",
            latency_ms=8,
            threshold=0.7,
        )


def test_jev_requires_base_url_and_is_opt_in() -> None:
    with pytest.raises(ValueError):
        JevJudge(base_url="", api_key=None)


class _FakeTransport:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests: list[dict] = []

    def post(self, url: str, *, payload: dict, headers: dict, timeout: int) -> dict:
        self.requests.append({"url": url, "json": payload, "headers": headers})
        return self.payload


def test_jev_classify_round_trip_via_transport() -> None:
    transport = _FakeTransport({"probabilities": {"correct": 0.91, "incorrect": 0.09}})
    judge = JevJudge(
        base_url="https://jev.example.test",
        api_key="secret",
        transport=transport,
        confidence_threshold=0.7,
    )
    verdict = judge.judge(JudgeRequest(question="Q", answer="A", reference_answer="R"))
    assert verdict.label is JudgeLabel.correct
    assert verdict.judge_name == "jev"
    assert transport.requests, "expected one classify call"
    sent = transport.requests[0]
    assert "secret" in sent["headers"]["authorization"]
    # Question/answer go into the classify input; no raw credentials elsewhere.
    assert "A" in str(sent["json"])
