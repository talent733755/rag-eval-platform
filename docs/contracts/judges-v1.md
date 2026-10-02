# Judges v1

`judges-v1` defines the **pluggable, deterministic** answer-quality judging contract.
A judge answers one bounded question per run item — is the generated answer correct
with respect to the reference answer and gold evidence? It returns a probabilistic
verdict plus a confidence score in `[0, 1]`.

## Hard rules

* **A judge verdict is never golden truth.** It is a low-cost, deterministic signal.
  Below the configured confidence threshold the platform marks the verdict
  `needs_review` and routes the item back to human review instead of acting on the
  label. Low-confidence verdicts are reported as `judge_low_confidence` missing values
  and never bias the `answer_correctness` metric.
* **Default-off and free.** The default judge is `noop`, which reports every item as
  `unavailable` at zero cost and zero egress. Judging is opt-in per deployment.
* **Pluggable.** The `JudgeProvider` protocol (`judges/protocol.py`) is swappable:
  `noop`, `rule-based` (offline lexical baseline), `jev` (TypeSafe System One decision
  model), or a future implementation. Selecting one is explicit configuration; an
  unknown kind degrades to `noop` rather than crashing a run.
* **No secrets in the contract.** The request carries only the question, generated
  answer, optional reference answer and gold evidence excerpts. Credentials, prompts
  and PII are stripped upstream; judge configuration (base URL, API key) lives in
  server settings, never in run snapshots.

## Verdict semantics

| Verdict | `answer_correctness` metric | Failure attribution |
| --- | --- | --- |
| `correct` (high confidence) | `1.0` | none |
| `incorrect` (high confidence) | `0.0` | eligible for `answer_incorrect` |
| low confidence (`needs_review`) | missing (`judge_low_confidence`) | routed to human review |
| `unavailable` / not run | missing (`judge_unavailable` / `judge_not_run`) | none |

A judge that is unavailable, times out, or returns a malformed payload raises
`JudgeUnavailableError`; the worker records the item with a NULL verdict so the metric
is reported missing, never fabricated.

## Jev judge

The `jev` implementation adapts answer-correctness onto Jev's
`classify(input, labels[], confidence_threshold)` contract over HTTP. It is fully
opt-in (requires an explicit base URL and API key), sends bounded secret-stripped
input, enforces a timeout, and is deterministic (probability-based, not sampled).
Jev's fast decision-model profile makes it suitable for CI regression gating where
LLM-as-judge cost and latency are prohibitive.

## Candidate quality gate

During candidate generation the configured judge also pre-screens each draft for
*consistency* between the reference answer and the source evidence. The verdict is
folded into the item's `automatic_checks.quality_gate` and surfaced in the review
queue. The gate is advisory: a confident *inconsistency* or a low-confidence verdict
flags the item for a human (`needs_human_review: true`) rather than auto-rejecting it.
With the default `noop` judge nothing is screened and no review signal is emitted.

## Configuration

* `JUDGE_KIND` — `noop` (default) | `rule-based` | `jev`.
* `JUDGE_CONFIDENCE_THRESHOLD` — probability threshold in `(0, 1]`; below it a verdict
  is `needs_review`.
* `JUDGE_JEV_BASE_URL` / `JUDGE_JEV_API_KEY` — required when `JUDGE_KIND=jev`.
