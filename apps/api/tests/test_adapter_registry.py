from __future__ import annotations

from typing import Any

from rag_eval_api.adapters.registry import load_python_adapter


class FakeEntryPoint:
    def __init__(self, loaded: Any) -> None:
        self.loaded = loaded

    def load(self) -> Any:
        return self.loaded


def test_registry_loads_exactly_named_trusted_entry_point(monkeypatch: Any) -> None:
    import rag_eval_api.adapters.registry as registry

    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda **kwargs: [FakeEntryPoint(lambda payload: {"request_id": payload["request_id"]})],
    )

    adapter = load_python_adapter(
        "fixture",
        adapter_version="fixture-v1",
        trace_level="minimal",
        timeout_seconds=2,
    )

    assert adapter.capability.adapter_version == "fixture-v1"


def test_registry_rejects_missing_or_ambiguous_entry_point(monkeypatch: Any) -> None:
    import pytest

    import rag_eval_api.adapters.registry as registry
    from rag_eval_api.adapters.errors import AdapterError

    monkeypatch.setattr(registry, "entry_points", lambda **kwargs: [])
    with pytest.raises(AdapterError, match="not installed"):
        load_python_adapter(
            "missing",
            adapter_version="fixture-v1",
            trace_level="minimal",
            timeout_seconds=2,
        )

    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda **kwargs: [FakeEntryPoint(object()), FakeEntryPoint(object())],
    )
    with pytest.raises(AdapterError, match="ambiguous"):
        load_python_adapter(
            "duplicate",
            adapter_version="fixture-v1",
            trace_level="minimal",
            timeout_seconds=2,
        )
