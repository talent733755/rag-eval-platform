"""answer_correctness metric driven by the configured judge verdict."""

from __future__ import annotations

from rag_eval_api.models import ExperimentRunItem, ExperimentRunItemStatus
from rag_eval_api.services.metric_calculation import METRIC_SPECS, _sample_value


def _item(judge: dict | None) -> ExperimentRunItem:
    item = ExperimentRunItem()
    item.status = ExperimentRunItemStatus.succeeded
    item.final_answer = "答案"
    item.final_judge = judge  # type: ignore[attr-defined]
    return item


def test_answer_correctness_spec_exists_in_generation_stage() -> None:
    spec = METRIC_SPECS.get("answer_correctness")
    assert spec is not None
    assert spec.stage == "generation"
    assert spec.kind == "judge_correctness"


def test_correct_verdict_scores_one() -> None:
    spec = METRIC_SPECS["answer_correctness"]
    value = _sample_value(
        spec,
        _item({"label": "correct", "confidence": 0.9, "needs_review": False}),
    )
    assert value.value == 1.0


def test_incorrect_verdict_scores_zero() -> None:
    spec = METRIC_SPECS["answer_correctness"]
    value = _sample_value(
        spec,
        _item({"label": "incorrect", "confidence": 0.8, "needs_review": False}),
    )
    assert value.value == 0.0


def test_unavailable_verdict_is_missing_not_zero() -> None:
    spec = METRIC_SPECS["answer_correctness"]
    value = _sample_value(spec, _item({"label": "unavailable"}))
    assert value.value is None
    assert value.missing_reason == "judge_unavailable"


def test_needs_review_verdict_is_missing_to_avoid_false_signal() -> None:
    """Low-confidence verdicts route to humans and must not bias the metric."""

    spec = METRIC_SPECS["answer_correctness"]
    value = _sample_value(
        spec,
        _item({"label": "incorrect", "confidence": 0.5, "needs_review": True}),
    )
    assert value.value is None
    assert value.missing_reason == "judge_low_confidence"


def test_no_judge_run_is_missing() -> None:
    spec = METRIC_SPECS["answer_correctness"]
    value = _sample_value(spec, _item(None))
    assert value.value is None
    assert value.missing_reason == "judge_not_run"
