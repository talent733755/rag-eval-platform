"""Versioned adapter contracts and implementations."""

from rag_eval_api.adapters.http import HttpAdapter
from rag_eval_api.adapters.protocol import (
    ADAPTER_CAPABILITY_VERSION,
    Adapter,
    AdapterCapability,
    AdapterRequest,
    AdapterResponse,
    Citation,
    TraceEnvelope,
    Usage,
)
from rag_eval_api.adapters.python_sdk import PythonSdkAdapter
from rag_eval_api.adapters.registry import load_python_adapter

__all__ = [
    "ADAPTER_CAPABILITY_VERSION",
    "Adapter",
    "AdapterCapability",
    "AdapterRequest",
    "AdapterResponse",
    "Citation",
    "TraceEnvelope",
    "Usage",
    "HttpAdapter",
    "PythonSdkAdapter",
    "load_python_adapter",
]
