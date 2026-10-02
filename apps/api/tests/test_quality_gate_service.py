"""Run quality gate: deterministic threshold pass/fail for CI regression gating."""

from __future__ import annotations

from rag_eval_api.services.quality_gate import (
    GateThreshold,
    evaluate_quality_gate,
)

LOWER_IS_BETTER = {"failure_rate", "average_latency_ms", "average_total_tokens"}


def _results(**values: float | None) -> dict[str, float | None]:
    return dict(values)


def test_all_thresholds_pass_when_metrics_meet_bounds() -> None:
    gate = evaluate_quality_gate(
        _results(success_rate=0.95, failure_rate=0.05),
        [
            GateThreshold(metric_key="success_rate", min_value=0.9),
            GateThreshold(metric_key="failure_rate", max_value=0.1),
        ],
    )
    assert gate.passed is True
    assert all(check.passed for check in gate.checks)


def test_below_min_threshold_fails_the_gate() -> None:
    gate = evaluate_quality_gate(
        _results(success_rate=0.80),
        [GateThreshold(metric_key="success_rate", min_value=0.9)],
    )
    assert gate.passed is False
    check = gate.checks[0]
    assert check.passed is False
    assert check.actual == 0.80
    assert check.reason == "below_min"


def test_above_max_threshold_fails_the_gate() -> None:
    gate = evaluate_quality_gate(
        _results(failure_rate=0.25),
        [GateThreshold(metric_key="failure_rate", max_value=0.1)],
    )
    assert gate.passed is False
    assert gate.checks[0].reason == "above_max"


def test_missing_metric_is_configurable_and_never_silently_passes_by_default() -> None:
    gate = evaluate_quality_gate(
        _results(),  # success_rate has no value (missing)
        [GateThreshold(metric_key="success_rate", min_value=0.9)],
    )
    assert gate.passed is False
    assert gate.checks[0].reason == "metric_missing"
    # Opt-in: a deployment may tolerate missing metrics, but never by default.
    tolerant = evaluate_quality_gate(
        _results(),
        [GateThreshold(metric_key="success_rate", min_value=0.9)],
        missing_is_pass=True,
    )
    assert tolerant.passed is True


def test_incomplete_run_status_blocks_the_gate() -> None:
    gate = evaluate_quality_gate(
        _results(success_rate=1.0),
        [GateThreshold(metric_key="success_rate", min_value=0.9)],
        run_status="running",
    )
    assert gate.passed is False
    assert gate.incomplete is True
    assert gate.checks[0].reason == "run_incomplete"


def test_latency_uses_lower_is_better_max_threshold() -> None:
    gate = evaluate_quality_gate(
        _results(average_latency_ms=1800.0),
        [GateThreshold(metric_key="average_latency_ms", max_value=1000.0)],
    )
    assert gate.passed is False
    assert gate.checks[0].reason == "above_max"
