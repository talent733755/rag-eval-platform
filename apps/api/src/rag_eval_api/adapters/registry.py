"""Resolve only trusted, installed Python Adapter entry points."""

from __future__ import annotations

from importlib.metadata import entry_points

from rag_eval_api.adapters.errors import AdapterError
from rag_eval_api.adapters.python_sdk import PythonSdkAdapter


def load_python_adapter(
    entrypoint_ref: str | None,
    *,
    adapter_version: str,
    trace_level: str,
    timeout_seconds: float,
) -> PythonSdkAdapter:
    """Load one installed ``rag_eval_adapter`` entry point by exact name."""

    if not entrypoint_ref:
        raise AdapterError(
            "adapter_entrypoint_unavailable",
            "Python adapter entry point is not configured.",
        )
    matches = list(entry_points(group="rag_eval_adapter", name=entrypoint_ref))
    if len(matches) != 1:
        raise AdapterError(
            "adapter_entrypoint_unavailable",
            "Python adapter entry point is not installed or is ambiguous.",
        )
    try:
        loaded = matches[0].load()
    except Exception as exc:
        raise AdapterError(
            "adapter_entrypoint_unavailable",
            "Python adapter entry point could not be loaded.",
        ) from exc
    if not callable(loaded):
        raise AdapterError(
            "adapter_entrypoint_invalid",
            "Python adapter entry point is not callable.",
        )
    return PythonSdkAdapter(
        loaded,
        adapter_version=adapter_version,
        trace_level=trace_level,
        timeout_seconds=timeout_seconds,
    )
