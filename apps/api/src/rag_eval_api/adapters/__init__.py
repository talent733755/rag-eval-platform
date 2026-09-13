"""Versioned adapter contracts and implementations."""

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

__all__ = [
    "ADAPTER_CAPABILITY_VERSION",
    "Adapter",
    "AdapterCapability",
    "AdapterRequest",
    "AdapterResponse",
    "Citation",
    "TraceEnvelope",
    "Usage",
]
