"""Run quality gate: deterministic threshold pass/fail for CI regression gating.

The gate is a pure function over a run's aggregate (`scope=run`) metric values and a
caller-supplied threshold set. It is the decision point a CI pipeline (e.g. the bundled
GitHub Action) uses to block a RAG change that regresses quality below an agreed floor.

Red lines:

* **Never silently pass.** A metric that is missing (never computed / unavailable)
  fails the gate by default; a deployment may opt into tolerating gaps, but absence of
  evidence is never treated as success.
* **An incomplete run cannot gate.** A run that has not finished (`succeeded` /
  `failed`) is reported `incomplete` and fails, so CI cannot gate on partial data.
* **Deterministic and auditable.** Every check records the actual value, the bound,
  and a stable machine-readable `reason`, so the verdict is reproducible and
  explainable in a build log.
"""

from __future__ import annotations

from dataclasses import dataclass, field

COMPLETE_RUN_STATUSES = frozenset({"succeeded", "failed"})


@dataclass(frozen=True, slots=True)
class GateThreshold:
    """A bound on one metric. At least one of min/max must be set."""

    metric_key: str
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True, slots=True)
class GateCheckResult:
    metric_key: str
    passed: bool
    actual: float | None
    min_value: float | None
    max_value: float | None
    reason: str


@dataclass(frozen=True, slots=True)
class RunQualityGate:
    passed: bool
    incomplete: bool = False
    checks: tuple[GateCheckResult, ...] = field(default_factory=tuple)


def evaluate_quality_gate(
    metrics: dict[str, float | None],
    thresholds: list[GateThreshold] | tuple[GateThreshold, ...],
    *,
    run_status: str = "succeeded",
    missing_is_pass: bool = False,
) -> RunQualityGate:
    """Evaluate a run against thresholds; pure and side-effect free."""

    incomplete = run_status not in COMPLETE_RUN_STATUSES
    checks: list[GateCheckResult] = []
    for threshold in thresholds:
        actual = metrics.get(threshold.metric_key)
        passed, reason = _check(threshold, actual, incomplete, missing_is_pass)
        checks.append(
            GateCheckResult(
                metric_key=threshold.metric_key,
                passed=passed,
                actual=actual,
                min_value=threshold.min_value,
                max_value=threshold.max_value,
                reason=reason,
            )
        )
    passed = all(check.passed for check in checks)
    return RunQualityGate(passed=passed, incomplete=incomplete, checks=tuple(checks))


def _check(
    threshold: GateThreshold, actual: float | None, incomplete: bool, missing_is_pass: bool
) -> tuple[bool, str]:
    if incomplete:
        return False, "run_incomplete"
    if actual is None:
        return (
            (True, "metric_missing_tolerated")
            if missing_is_pass
            else (
                False,
                "metric_missing",
            )
        )
    if threshold.min_value is not None and actual < threshold.min_value:
        return False, "below_min"
    if threshold.max_value is not None and actual > threshold.max_value:
        return False, "above_max"
    return True, "ok"
