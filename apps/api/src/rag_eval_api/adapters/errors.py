"""Stable errors exposed by adapter implementations."""

from __future__ import annotations


class AdapterError(RuntimeError):
    """Safe adapter failure with a stable code and retry hint."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class AdapterUnavailableError(AdapterError):
    """The adapter endpoint cannot currently serve the request."""
