"""Jev judge client: deterministic decision-model classification over the real /systemone contract."""

from __future__ import annotations

import pytest

from rag_eval_api.judges.jev import (
    CORRECT_OPTION,
    INCORRECT_OPTION,
    QUESTION_KEY,
    JevJudge,
    _build_payload,
    _build_state,
    _parse_verdict,
)
from rag_eval_api.judges.protocol import JudgeLabel, JudgeRequest


def test_build_state_is_bounded_and_structured() -> None:
    state = _build_state(JudgeRequest(question="问题", answer="答案", reference_answer="参考"))
    assert "答案" in state and "参考" in state and "问题" in state
    assert len(state) < 100_000


def test_build_payload_uses_choice_question_with_criteria() -> None:
    payload = _build_payload(
        JudgeRequest(question="Q", answer="A", reference_answer="R"), model="jev-latest"
    )
    assert payload["model"] == "jev-latest"
    question = payload["questions"][QUESTION_KEY]
    assert question["type"] == "choice"
    assert set(question["options"]) == {CORRECT_OPTION, INCORRECT_OPTION}
    assert set(question["criteria"]) == {CORRECT_OPTION, INCORRECT_OPTION}


def test_parse_verdict_maps_choice_to_label() -> None:
    verdict = _parse_verdict(
        {"answers": {QUESTION_KEY: {"type": "choice", "choice": "correct", "confidence": 0.93}}},
        judge_name="jev",
        judge_version="judge-v1",
        latency_ms=8,
        threshold=0.7,
    )
    assert verdict.label is JudgeLabel.correct
    assert verdict.confidence == pytest.approx(0.93)
    assert verdict.needs_review is False


def test_parse_verdict_maps_incorrect_choice() -> None:
    verdict = _parse_verdict(
        {"answers": {QUESTION_KEY: {"type": "choice", "choice": "incorrect", "confidence": 0.88}}},
        judge_name="jev",
        judge_version="judge-v1",
        latency_ms=8,
        threshold=0.7,
    )
    assert verdict.label is JudgeLabel.incorrect
    assert verdict.confidence == pytest.approx(0.88)


def test_parse_verdict_low_confidence_routes_to_review() -> None:
    verdict = _parse_verdict(
        {"answers": {QUESTION_KEY: {"type": "choice", "choice": "correct", "confidence": 0.55}}},
        judge_name="jev",
        judge_version="judge-v1",
        latency_ms=8,
        threshold=0.7,
    )
    assert verdict.confidence < 0.7
    assert verdict.needs_review is True


@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": True},
        {"answers": {}},
        {"answers": {QUESTION_KEY: {"type": "choice", "choice": "maybe", "confidence": 0.9}}},
        {"answers": {QUESTION_KEY: {"type": "choice", "choice": "correct"}}},
    ],
)
def test_parse_verdict_rejects_malformed_payload(payload: dict) -> None:
    with pytest.raises(ValueError):
        _parse_verdict(
            payload,
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


def test_jev_systemone_round_trip_via_transport() -> None:
    transport = _FakeTransport(
        {"answers": {QUESTION_KEY: {"type": "choice", "choice": "correct", "confidence": 0.91}}}
    )
    judge = JevJudge(
        base_url="https://jev.example.test/v1",
        api_key="secret",
        transport=transport,
        confidence_threshold=0.7,
    )
    verdict = judge.judge(JudgeRequest(question="Q", answer="A", reference_answer="R"))
    assert verdict.label is JudgeLabel.correct
    assert verdict.judge_name == "jev"
    assert transport.requests, "expected one systemone call"
    sent = transport.requests[0]
    assert sent["url"] == "https://jev.example.test/v1/systemone"
    assert "secret" in sent["headers"]["authorization"]
    # Question/answer go into the bounded state; no raw credentials elsewhere.
    assert "A" in sent["json"]["state"]
