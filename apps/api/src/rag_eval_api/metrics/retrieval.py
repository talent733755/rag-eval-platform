"""Deterministic retrieval metrics with explicit empty-set semantics."""

from __future__ import annotations

import math
from collections.abc import Sequence


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _top(values: Sequence[str], k: int) -> list[str]:
    return _unique(values)[:k]


def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float | None:
    relevant = set(_unique(relevant_ids))
    if not relevant:
        return None
    return len(set(_top(retrieved_ids, k)) & relevant) / len(relevant)


def precision_at_k(
    retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int
) -> float | None:
    top = _top(retrieved_ids, k)
    if not top:
        return None
    return len(set(top) & set(_unique(relevant_ids))) / len(top)


def hit_rate_at_k(
    retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int
) -> float | None:
    relevant = set(_unique(relevant_ids))
    if not relevant:
        return None
    return float(bool(set(_top(retrieved_ids, k)) & relevant))


def mean_reciprocal_rank(retrieved_ids: Sequence[str], relevant_ids: Sequence[str]) -> float | None:
    relevant = set(_unique(relevant_ids))
    if not relevant:
        return None
    for index, item_id in enumerate(_unique(retrieved_ids), start=1):
        if item_id in relevant:
            return 1 / index
    return 0.0


def ndcg_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float | None:
    relevant = set(_unique(relevant_ids))
    if not relevant:
        return None
    dcg = sum(
        1 / math.log2(index + 2)
        for index, item_id in enumerate(_top(retrieved_ids, k))
        if item_id in relevant
    )
    ideal_length = min(len(relevant), k)
    ideal = sum(1 / math.log2(index + 2) for index in range(ideal_length))
    return dcg / ideal if ideal else None
