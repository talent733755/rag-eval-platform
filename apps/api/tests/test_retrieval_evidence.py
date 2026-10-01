"""Retrieval evidence extraction from persisted traces (adapter-v2 contract)."""

from __future__ import annotations

from rag_eval_api.services.retrieval_evidence import (
    extract_retrieved_chunk_ids,
    resolve_relevant_chunk_ids,
)


def test_extracts_ordered_ids_from_structured_retrieval_stage() -> None:
    stages = [
        {"name": "rewrite", "payload": {"query": "q"}},
        {"name": "retrieve", "payload": {"ids": ["chunk-1", "chunk-2", "chunk-1"]}},
        {"name": "generate", "payload": {"text": "answer"}},
    ]

    assert extract_retrieved_chunk_ids(stages, stage_names=("retrieve",)) == [
        "chunk-1",
        "chunk-2",
        "chunk-1",
    ]


def test_prefers_last_retrieval_stage_when_multiple_exist() -> None:
    stages = [
        {"name": "retrieve", "payload": {"ids": ["old"]}},
        {"name": "rerank", "payload": {"ids": ["new-a", "new-b"]}},
    ]

    # rerank is the final ordering of candidates for the generator.
    assert extract_retrieved_chunk_ids(stages, stage_names=("rerank",)) == ["new-a", "new-b"]


def test_returns_empty_when_no_structured_ids_present() -> None:
    stages = [{"name": "generate", "payload": {"text": "answer"}}]

    assert extract_retrieved_chunk_ids(stages) == []


def test_ignores_non_list_or_empty_ids() -> None:
    stages = [
        {"name": "retrieve", "payload": {"ids": "not-a-list"}},
        {"name": "retrieve2", "payload": {"ids": []}},
    ]

    assert extract_retrieved_chunk_ids(stages) == []


def test_handles_missing_payload_or_name_safely() -> None:
    stages = [
        {"name": "retrieve"},  # no payload
        {"payload": {"ids": ["x"]}},  # no name
        {"name": "retrieve", "payload": {"ids": ["ok"]}},
    ]

    assert extract_retrieved_chunk_ids(stages) == ["ok"]


def test_resolve_relevant_ids_maps_gold_chunk_uuids_to_strings() -> None:
    from uuid import uuid4

    a, b = uuid4(), uuid4()
    assert resolve_relevant_chunk_ids([a, b]) == [str(a), str(b)]


def test_resolve_relevant_ids_preserves_string_ids() -> None:
    assert resolve_relevant_chunk_ids(["chunk-1", "chunk-2"]) == ["chunk-1", "chunk-2"]
