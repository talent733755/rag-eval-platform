import pytest

from rag_eval_api.metrics.protocol import MetricResult, RetrievalInput
from rag_eval_api.metrics.retrieval import (
    hit_rate_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_retrieval_metrics_are_bounded_and_deduplicate_results() -> None:
    retrieved = ["a", "a", "b", "c"]
    relevant = ["b", "c"]

    assert recall_at_k(retrieved, relevant, 2) == pytest.approx(0.5)
    assert precision_at_k(retrieved, relevant, 2) == pytest.approx(0.5)
    assert hit_rate_at_k(retrieved, relevant, 2) == 1.0
    assert mean_reciprocal_rank(retrieved, relevant) == pytest.approx(1 / 2)
    assert 0 <= (ndcg_at_k(retrieved, relevant, 2) or 0) <= 1


def test_empty_relevance_is_explicitly_missing_and_no_hit_is_zero() -> None:
    assert recall_at_k(["a"], [], 5) is None
    assert precision_at_k([], ["a"], 5) is None
    assert hit_rate_at_k(["b"], ["a"], 5) == 0.0
    assert mean_reciprocal_rank(["b"], ["a"]) == 0.0


def test_metric_contract_keeps_version_and_missing_value_provenance() -> None:
    input_data = RetrievalInput(retrieved_ids=["a"], relevant_ids=[], k=5)
    result = MetricResult(
        metric_name="recall@5",
        version="retrieval-v1",
        value=None,
        sample_count=1,
        missing_reason="no_relevant_evidence",
        provenance={"k": str(input_data.k)},
    )
    assert result.missing_reason == "no_relevant_evidence"
