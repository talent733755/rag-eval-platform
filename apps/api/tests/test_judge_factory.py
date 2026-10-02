"""Judge provider factory: config-driven, default-off, safe fallback."""

from __future__ import annotations

import pytest

from rag_eval_api.judges.factory import build_judge_provider
from rag_eval_api.judges.noop import NoopJudge
from rag_eval_api.judges.rule_based import RuleBasedJudge


def test_default_is_noop_and_free() -> None:
    judge = build_judge_provider(kind="noop")
    assert isinstance(judge, NoopJudge)


def test_rule_based_kind_selected() -> None:
    judge = build_judge_provider(kind="rule-based")
    assert isinstance(judge, RuleBasedJudge)


def test_jev_requires_base_url() -> None:
    with pytest.raises(ValueError):
        build_judge_provider(kind="jev", jev_base_url=None)


def test_jev_kind_builds_with_config() -> None:
    judge = build_judge_provider(
        kind="jev",
        jev_base_url="https://jev.example.test",
        jev_api_key="key",
        confidence_threshold=0.8,
    )
    assert judge.name == "jev"


def test_unknown_kind_falls_back_to_noop_not_crash() -> None:
    judge = build_judge_provider(kind="does-not-exist")
    assert isinstance(judge, NoopJudge)
